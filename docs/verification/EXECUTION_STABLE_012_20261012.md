# Execution0.1.2 final runtime acceptance / 最终运行验收

Main independently verified each stage before publication. The entries below this final section are historical checkpoints; their pending/failure states are retained and do not describe the final candidate. / Main已逐项复核最终证据；以下历史检查点保留当时待验或失败状态，不代表当前候选。

| Stage / 阶段 | Evidence directory / 证据目录 | Result / 结果 |
|---|---|---|
| Main source / 源码 | execution-012-ddg-numpy-source-main-01 | First complete attempt passed / 首次整套通过 |
| Main installed / 安装 | execution-012-ddg-numpy-installed-main-01 | First complete attempt passed / 首次整套通过 |
| Independent Sol installed / 独立安装验收 | execution-012-ddg-numpy-installed-sol-01 | First complete attempt passed / 首次整套通过 |

Each ran DuckDuckGo → NumPy ndarray documentation → first matching numpy.org ordinary result twice in the same window/session, then authenticated zero-input cancellation and normal owned-window/host cleanup. Each used20 Decision and7 grounding requests with0 automatic retries; cache/profile were retained. Main inspected final original evidence; titles and ndarray array-object text are visible. / 三阶段各连续两轮、零输入取消与正常收尾通过；各20次Decision+7次定位，无重试、无缓存清理，最终原图可读。

Accepted runtime: source manifest27 SHA256 f15e705012208ce21ea89e38cec9b0990c5cd7e25e583038e0712f87b2754640 (609 delivered sources/resources). Candidate06 Setup SHA256 d2339c35160df12f6cdc3977b8f741c7ace4617f6fddd90cbb18e9385f04c80f; installed611 payload files verified. Candidate06 is the actual live-tested package. Final packaging updates documentation only and must retain all accepted non-Markdown delivered bytes; package dependency and install/hash verification remain separate from live acceptance. / 实机验收归属candidate06；最终文档收尾包装必须保持已验非Markdown交付字节一致，依赖及安装哈希检查单独记录。

Main final execution release-scope regression: 4046 passed,0 failed/errors,1 skipped (execution-release-scope-final.xml). The symlink-redirection check is skipped if Windows denies symlink creation. Field production wire:19/19 exact tested payloads. Earlier targeted groups overlap and are not summed. / 最终执行版范围回归4046项通过、1项跳过：Windows未授权创建符号链接时，目录重定向测试无法运行；字段19份正式请求与实测一致，其他重叠测试不相加。

The first scope regression recorded4030 passes,16 failures and1 environment skip. Repairs added a missing linked document to package resources and corrected tests for the accepted two-check input path, margin rendering, deterministic status-query timing and the earlier authenticated-binding rejection. Runtime bytes were unchanged by these test/package repairs. The failed XML is retained separately. / 首次范围回归4030通过、16失败、1项环境跳过；补齐漏包文档，并修正已验双审核输入路径、外沿标记、查询时序及更早绑定拒绝的旧测试预期。这批修复未改运行代码，失败记录独立保留。

Installed Main request measurements:20 Decisions,22,930 input tokens. Field HTTP142.1371–183.6346ms (median153.11285); candidate188.168–541.5443ms; submit candidate172.6532–215.9254ms; current result208.4718–275.9316ms. These exclude grounding, image preparation, native input and loading. No general accuracy or whole-task speedup is claimed. / 以上仅单请求数据，不宣称通用准确率或整任务提速。

Learning remains0.1.0-preview.3 and is not rebuilt. Earlier candidate04/05, git-diff and curl failures remain below and in their original private receipts. Target wording limitations are recorded in [Decision usage](DECISION_TARGET_USAGE_20261013.md). / 学习包不更新，历史失败不改写。

## 2026-10-13 Action-stage timing read-back / 动作阶段计时回读

This documentation update reads the retained installed Main acceptance; it does not represent a new runtime test. The task was DuckDuckGo → search “NumPy ndarray documentation” → first matching official NumPy result. / 本次文档更新回读已有安装版 Main 验收记录，不代表新跑一轮测试；任务为 DuckDuckGo → 搜索“NumPy ndarray documentation” → 首个匹配的 NumPy 官方结果。

| Round / 轮次 | Input action / 输入动作 | Recorded total_ms / 原始毫秒 | Execution request / 执行请求 |
|---|---|---|---|
| 1 | open_ddg | 9543.943 | `trial-exec-d741b255f595ee8392efbb09910aa2d0` |
| 1 | search_numpy | 10137.636 | `trial-exec-5d19e9dfe55e5c4c0870702f7a4964d0` |
| 2 | open_ddg | 9175.648 | `trial-exec-b539c3da69e13926fc9f9db1cac4fefa` |
| 2 | search_numpy | 9126.013 | `trial-exec-e95658e214b7e07110417ca3523f54e5` |

Rounded ranges: **9.2–9.5 seconds for the address action; 9.1–10.1 seconds for the search action**. The recorded input-sequence total includes grounding, input execution and post-action capture. The plan's final page-result verification is separate, as is outer task orchestration. These are action-stage durations, not whole-task latency or API-only response times. / 四舍五入后：**地址动作 9.2–9.5 秒，搜索动作 9.1–10.1 秒**。输入序列计时包含定位、输入执行及动作后截图；计划层最终页面结果审核和外部任务调度另计。这是动作阶段耗时，不是整任务总时长或仅 API 响应时间。

Evidence root: `D:/AgentReviewAcceptance/execution-012-ddg-numpy-installed-main-01`. Read each step's `execution_request_id` from `round-1.response.json` / `round-2.response.json`, then use `result.total_ms` from the completed `runtime/session-6afd42a45bd54410b0b89f94b9db23ca/agent-commands/<execution_request_id>.json`. Early pending/poll receipts are not action totals. The final link-click action has no equivalent recorded total, so no third-action duration is published. / 按两轮回执中的执行请求 ID，读取已完成 agent-command 的 `result.total_ms`；早期 pending／轮询回执不能当作动作总耗时。最后一次链接点击没有相同口径的总计时，因此不发布第三个动作耗时。

The same two-round acceptance, including cancellation verification, used **20 Decision requests, 22,930 Decision input tokens and 7 separate visual-grounding requests**. Grounding token usage is additional. No matching successful old-version baseline exists for this task and timing boundary, so no per-action seconds saved, percentage speedup or token reduction is claimed. / 同一两轮验收（含取消检查）为 **20 次 Decision、22,930 个 Decision 输入 token，另加 7 次视觉定位请求**；定位 token 另计。缺少同任务、同边界且完整成功的旧版基线，不宣称每步节省秒数、提速百分比或 token 降幅。

---

## Historical checkpoint: installed candidate04 field-value failure / 历史检查点：安装候选04字段值误判

Execution 0.1.2 remains unpublished; learning is unchanged. The fresh source Bing→MDN attempt passed two rounds, authenticated zero-input cancellation and normal cleanup. Installed candidate04 then failed its first `search_mdn_map` field-value review: the correct dark entered text was rejected before Enter, while a diagnostic expected value including gray unaccepted `guide` was falsely accepted. The installed first-attempt summary remains failed with zero completed rounds and cancellation unverified; normal cleanup did not convert it into a pass. Three prompt/crop diagnostic groups did not classify both controls correctly, and none was adopted. No independent live acceptance has occurred; browser profile/cache remain preserved. / 执行 0.1.2 尚未发布，学习版不变。全新源码 Bing→MDN 首次整套两轮、认证的零输入取消及正常收尾通过；安装候选04却在首轮 `search_mdn_map` 字段值审核误拒深色正确已输入值，Enter 前停止；诊断中含灰色未接受 `guide` 的错误期望反而被判通过。安装版首次摘要仍为失败、零完整轮次、取消未验证；正常收尾不改记通过。三组提示词／裁图诊断均未同时判对正反例，未被采纳；尚无独立实机验收，浏览器资料和缓存保留。

## 2026-10-13 Current verified source / 当前已验证源码

manifest18 freezes 608 delivered files (SHA256 4cd4623de3a56761def05e11897941c906304485cb8587778931bd0d22fe1967). The three-address regression05 passed, with 12 Decision and3 grounding calls. A different fresh Bing→search 维基百科 地球→Chinese Wikipedia Earth flow passed its first entire attempt: two automatic rounds, authenticated zero-input cancellation, normal owned-window/host cleanup;20 Decision,7 grounding,23,438 Decision input tokens. Sources stayed unchanged and the retained browser profile/cache were preserved. / manifest18冻结608个交付文件，三次地址回归通过；不同新流程首次整套两轮、零输入取消及正常收尾通过，运行中源码未变，缓存保留。

Evidence roots: D:/AgentReviewAcceptance/execution-012-enter-diagnostic-05 and execution-012-bing-earth-01. Offline:231 checks in15.07s, then92 proxy-related checks in6.93s (overlapping groups, not additive). Regression04 failed because the command proxy repeated grounding and passed a duplicate argument; this is preserved separately from the fixed result. No general accuracy or end-to-end speedup claim. At this manifest18 source freeze, installed candidate, independent acceptance and publication were still pending; later installed results are below. / 原代理漏接首败保留；测试组有重叠，不相加。在此 manifest18 源码冻结时安装、独立验收及发布仍待完成；后续安装结果见下文。不宣称通用准确率或整体提速。

## 2026-10-13 Decision usage fix / Decision用法修正

Failure: EV1 entered the complete Records path but text Choice rejected it. Root contract: current text must be judged from a legible, correctly bound field image without future field-operation instructions. Fix: common provider plus field_value_view render the complete annotated ROI at 2× and send only expected_text and the text comparison. This applies to supported fields across apps, not an Explorer-specific rule. No threshold, wait, retry or extra request changed. / 故障是已正确输入却误拒；通用修复位于provider与field_value_view，完整字段标图2倍放大，只问规定文字，不混入后续字段操作；不改阈值、等待、重试或调用次数。

Evidence: old exact request repeated its false rejection (589 input tokens); compact question alone falsely accepted a Recordx single-character counterexample and was rejected as a design. Compact+2× matched both labels, with 397/398 tokens (about32.6% less for the positive case); its production wire is byte-identical to that successful diagnostic. Actual production field calls: met/not_met, HTTP143.41/595.16ms. These are selected-image results, not a general accuracy or speed benchmark. / 原请求复现误拒，单纯缩短问题误放单字符反例，未采用；放大加精简正反均正确，生产wire与诊断完全一致。

Candidate prompt also removes click-consumption prediction and explicitly excludes unrelated nonblocking popups, following the user's scope. The final 6-case provider probe matched5 preset labels; old popup-input02 changed from the prior expected not_met to met (.45/.37/.18). Preserve this mismatch: its visible popup does not cover the marked address field, but static evidence does not prove actual click delivery. Do not claim6/6 or infer full workflow success from these image probes. / 候选问题按用户要求删去吞点击预测，明确无关不阻挡弹窗不单独否决；最终6例中5例符合旧预设，popup02由旧预设拒绝变为通过。保留此差异，静态图不能证明点击实际送达，不称6/6，也不据此宣称全流程成功。

Main offline:156 passed in12.25s, field-value-provider-main-green2.xml; worker renderer/old annotation61 passed in0.69s (groups overlap). Earlier red and stale-wire-assertion failures are preserved. Regression checks original metadata/expected-text tampering, source immutability, mapping bounds and one-request behavior. Safety: native authorization, action taxonomy, identity/geometry, cancel/deadline and value-before-Enter checks remain intact; no speculative click/focus check added. / 离线及原始失败均保留，原绑定与权限门禁未放松。下一步新流程实测，再构建/安装/独立验收；尚未发布。

## 2026-10-13 Explorer EV1 — field-value false rejection / 字段值误拒

Main verified the original screenshot: the complete requested Records path was entered, but text-only Choice returned condition_not_met (.96, met .03, insufficient .01; HTTP 195.08ms, 589 input tokens). Enter was not sent. Candidate acceptance succeeded; the failure is the current value judgment, not empty-field/focus detection. The uploaded annotated ROI was 795×55. No threshold, wait, retry or source changes were made. Two rounds/cancellation were not reached; owned window and host closed normally, fixtures and manifest14 remained unchanged. / Main核对原图，完整Records路径已输入，但文字Choice误拒；未按Enter。候选通过，问题在当前文字判读。标注裁剪图795×55；阈值、等待、重试及源码未改。本轮整套首验失败，本轮窗口与宿主正常关闭，资料及manifest14未变。

Next: compare retained-image request methods (legibility, annotation and prompt) before further live acceptance. Evidence: D:/AgentReviewAcceptance/execution-012-explorer-view-01. Build03 and release remain pending. / 下一步先对保留图比较可读性、标注和提示词用法，再继续实测；尚未构建build03或发布。

## 2026-10-13 Python-ZH PZ1 current checkpoint / 当前检查点

The first Python 3.14 category-browsing attempt completed address input and opening Python built-ins reference automatically. Its third Built-in Functions link was below the visible viewport: Luna returned request_absent, no third input or Decision was dispatched. Main verified the original screenshot; this is a missing visible target, not a Decision false rejection. The three-step plan omitted the needed scroll. The first whole attempt remains failed with 0 complete rounds and no dedicated cancellation coverage. / Python 3.14分类浏览首验自动完成前两步，第三步内置函数链接不在当前可见区域，Luna返回request_absent，未派发该动作或Decision。Main核对了原图，这是目标未显示及原计划遗漏滚动，不是Decision误拒；首次整套仍失败，0完整轮，独立取消覆盖未达到。

Owned window and host closed normally; no forced close, retry, profile reset or cache deletion. Original evidence remains at D:/AgentReviewAcceptance/execution-012-python-zh-docs-01. Frozen manifest13 has 605 files / SHA256 2a6f62a75570c3f8f69a70cd7f56c4693a2f70eb55937cb0a6808aca6347f679, unchanged during execution. / 本轮窗口与宿主正常关闭，无强关、重试、资料重置或缓存删除，manifest13运行中未变。

No production code changed after the verified candidate-view optimization. Next is a different real File Explorer view-setting workflow; build03, installed/independent acceptance and release remain pending. / 候选视图优化验证后未再改生产源码；下一步不同的文件资源管理器显示方式工作流，build03、安装/独立验收和发布仍待完成。

## 2026-10-13 MDN M1 current checkpoint / 当前检查点

MDN M1 首次整套未通过：网址输入与 Statements 页面结果自动成功，第二步 if...else 点位正确，但当前截图含 Edge 翻译弹层，Choice 返回 condition_not_met（0.50；met 0.48；insufficient 0.02），未派发该点击。HTTP 202.9082ms、输入1076 tokens。仅凭截图尚不能确定弹层是否消费点击，不认定为新的 Decision 误拒，也不降低阈值。 / MDN M1 failed its first whole attempt. Address input and the Statements outcome succeeded automatically; the next if...else point was correct, but an Edge translation popup was visible and Choice rejected it before dispatch (unmet .50, met .48, insufficient .02; HTTP 202.9082ms, 1076 input tokens). The screenshot alone does not establish whether the popup consumes the click; this is not classified as a new false rejection and thresholds are unchanged.

4 Decision requests, 0 complete rounds; the dedicated cancellation-coverage probe was not reached. The original wait was cancelled and owned window/host closed normally. Profile, cache and extensions retained; no retry. Manifest12: 605 files, SHA256 34ecd20cab81b53d1743f4b8cfe151d8349956372a7f42e2bd12e54b562c49e2; source unchanged during run. Evidence: D:/AgentReviewAcceptance/execution-012-mdn-docs-01/flow-summary.json and round-1-execution-2.json. / 4次Decision、0完整轮，独立取消覆盖探针未到达；原等待取消和正常收尾成功，资料、缓存、扩展均保留，无重试，运行中源码未变。

The candidate-view optimization and four-case API comparison remain valid bounded evidence, not unattended acceptance. Next: a different public-document navigation task; no build03 or release yet. / 候选视图优化与4例API对照仍为有效单项证据，不代表无人干预验收；下一步不同公开文档导航流程，build03和发布仍未执行。

# Execution 0.1.2 stable release / 执行 0.1.2 正式版

## 2026-10-13 Candidate evidence usage / 候选证据用法

候选 Choice 的生产 provider 已改为同一次请求的一张概览＋细节 PNG：overview 最长边640px，完整候选框及附近上下文的 detail 最长边768px，小目标最多2倍；空心标记保留中心±6px。模型仅接收当前目标、动作kind、必要映射及当前allowed states/popup事实；原SHA、窗口身份、几何与账本认证仍留本地，旧v1标注和无标注回执兼容。阈值、wait、重试及输入后仅比文字的合同不变。 / The production candidate Choice provider now sends one overview/detail PNG in the existing request: a 640px maximum-edge overview and a complete-box detail with nearby context, a 768px maximum edge and up to 2× scaling for small targets. Hollow marks preserve ±6px around the center. Only the current target, action kind, necessary mapping and current allowed states/popup facts reach the model; full hashes, identity, geometry and ledger authentication remain local, including legacy v1 marked/unmarked receipts. Thresholds, wait/retry policy and text-only post-input checks are unchanged.

新视图仅用于单帧before-action、`CANDIDATE_CONDITION`、candidate scope、Choice、有有效`permitted_action.kind`且无freshness的路线；其他predicate/custom/freshness/multi-frame/unmarked/缺省permitted action保留原wire。输入动作逐字保留原交互弹层可行性说明，不增加截图、API请求、点击后焦点/空框检查或未来结果要求。 / The new view applies only to single-frame before-action Choice candidate review under `CANDIDATE_CONDITION`, with valid `permitted_action.kind` and no freshness context. Other predicate/custom/freshness/multi-frame/unmarked/omitted-permitted-action routes retain their previous wire. Input actions retain the original popup-feasibility clarification verbatim; no capture, API request, post-click focus/empty check or future-result requirement is added.

初始8次对照中，旧整图十字误拒SELECT、误放行合成错点UPDATE；普通composite仍拒SELECT但能拒错点。小字detail最多2倍后，两次分别SELECT met 0.65、错UPDATE notmet 0.51，各1050 input tokens，HTTP 282.233/256.834ms。该对照不能确定模型内部原因。 / In the initial eight calls, the old full-frame cross rejected SELECT and accepted the synthetic UPDATE wrong point. Ordinary composite still rejected SELECT but rejected the wrong point. With small detail text scaled up to 2×, SELECT was met (0.65) and wrong UPDATE unmet (0.51), each with 1050 input tokens and HTTP times of 282.233/256.834ms. This does not establish the model's internal cause.

| Case / 样本 | Old Choice / 旧 | Production Choice / 正式payload | Input tokens old→new | Production HTTP ms |
| --- | --- | --- | --- | --- |
| SELECT | condition_not_met | condition_met | 2280→1075 | 504.154 |
| Synthetic UPDATE wrong point / 合成错点 | condition_met | condition_not_met | 2286→1075 | 198.252 |
| Popup blocks input / 弹层阻挡 | condition_not_met | condition_not_met | 2662→1183 | 209.656 |
| Input without popup / 无弹层 | condition_met | condition_met | 2614→1131 | 194.206 |

正式payload的4个保留图正反例均符合预设判断：SELECT满足、合成错点UPDATE不满足、翻译弹层阻挡不满足、无弹层输入可行满足。Input tokens约少53–57%；0桌面动作、无动作授权、未采用结果、无自动重试。小样本不证明通用准确率、速度或部署通过。 / Four retained-image production-payload cases matched preset labels: SELECT met, synthetic UPDATE wrong point unmet, popup-blocked input unmet and unobstructed input met. Input tokens fell about 53–57%. There were no desktop actions, action authority, result adoption or automatic retries. This small sample establishes no general accuracy, speed or deployment acceptance.

HTTP时间不包含本地准备。4例各5次无API测量的render中位26.76–31.88ms，组包至mock HTTP中位29.53–34.09ms（含render）；wire摘要与正式请求相同。 / HTTP times exclude local preparation. Five local, API-free measurements per case gave median rendering of 26.76–31.88ms and packaging through mock HTTP of 29.53–34.09ms including rendering, with identical production wire digests.

离线：Main 133 passed in 1.81s（`candidate-view-main.xml`）、集成93 passed in 12.69s（`candidate-view-integration-main.xml`），worker25 passed in 0.94s（`candidate-view-provider-green.xml`）；重叠不相加。 / Offline: Main passed 133 in 1.81s, integration 93 in 12.69s and the worker 25 in 0.94s; these overlapping groups are not summed.

证据 / Evidence: `.superpowers/sdd/2026-10-12-execution-stable/candidate-usage-probe-02/` 中 `live-results.json`（初始8次）、`live-results-zoom.json`（2次）、`production/live-results.json`（正式4次）、`production/local-preparation.json`。原图、recipe与wire摘要保留；本次文档同步没有调用API。 / Original images, recipes and wire hashes are retained; this documentation update made no API call.

SQLite S1首次两步完成、第三步SELECT派发前误拒的整套失败保留；18.8248%区域变化经同一次当前帧Choice后完成输入，只属共享路径单项证据。不同的新MDN流程尚未运行。build03尚不存在、未构建，build02为旧候选；新冻结待产出，S1的manifest11不是本轮最终候选。执行0.1.2未发布，安装及同冻结候选独立验收待完成，学习包不更新。 / SQLite S1 remains a failed first whole attempt: two steps completed before SELECT was rejected without dispatch. Its 18.8248% region change reached the existing current-frame Choice and input completed, proving only that shared single-operation behavior. The different fresh MDN flow has not run. Build03 does not exist or have a build; build02 is older. A new freeze is pending and S1's manifest11 is not this revision's final candidate. Execution 0.1.2 is unpublished; installed and independent same-candidate acceptance remain pending, and learning is unchanged.

## 2026-10-13 SQLite S1 and candidate-evidence work / SQLite S1与候选证据优化

SQLite S1 首次整套未通过：首轮地址输入及 SQL Syntax 跳转完成，第三步 SELECT 在派发前被 Choice 判为 condition_not_met（0.51；met 0.38；insufficient 0.11）。Main核对原图，SELECT可见且点(868,596)位于链接内；模型内部误判原因尚不能由分数确定。该步零输入，整轮0、Decision 6次、grounding 3次。原run正常取消，owned窗口和host正常关闭，资料、缓存和扩展保留；独立取消覆盖未到达。 / The first whole SQLite S1 attempt failed after successful address input and SQL Syntax navigation. Choice rejected SELECT before dispatch. Main found the visible link and intended point aligned, but the model’s internal reason is unproven. Six Decision and three grounding calls were used, with zero complete rounds; the original run and owned resources closed normally and the retained profile was preserved.

R1共享修复已获得单项真实证据：S1地址栏像素变化18.8248%，通过同一次当前帧Choice审核后完成输入，未增加模型请求。完整无人干预验收仍未通过。 / S1 exercised the shared R1 correction: an 18.8248% address-field change passed its existing current-frame Choice and completed input. This is single-operation evidence, not whole-flow acceptance.

候选用法已完成源码接线及保留图API对照，见上方本轮记录；该单项对照不构成整套验收通过，不重放S1，原图和首次失败记录保留。 / Candidate evidence usage is wired in source and checked on retained images above. This targeted comparison is not whole-flow acceptance; S1 is not replayed and its original images and first failure remain unchanged.

原件 / Evidence: `D:/AgentReviewAcceptance/execution-012-sqlite-docs-01/flow-summary.json`; `runtime/session-ed6cfb8ce1874848a90c90b1213d94ae/agent-commands/trial-exec-1dbdb231acc88c872ae2f6bf2aa3eb16.json`. Manifest11 SHA-256 `69407c9ae418ed3150498b863f6827742348eced947e187fd17968e8cffc3328` remained unchanged. Execution 0.1.2 is not built/published; learning is unchanged. / 执行0.1.2未构建新候选或发布，学习不变。


## 2026-10-13 Rust docs R1 first whole attempt / Rust docs R1首次整体验收

Rust docs R1（`execution-012-rust-docs-01`）首次整套**未通过**：0完整round、0 Decision、1 grounding、0 input。源码在 `AgentGroundingTarget.plan` 以 `agent_grounding_target_region_changed` 于Decision前拒绝，`action_executed=false`；不是Decision误拒。 / Rust docs R1 **failed its first whole attempt**: zero complete rounds, zero Decision calls, one grounding call and zero input. `AgentGroundingTarget.plan` rejected with `agent_grounding_target_region_changed` before Decision, with no executed action; this was not a Decision false rejection.

Main/审查核对原图：源地址栏为已选中的about:blank、白底蓝边；当前为Tampermonkey更新URL、灰底。bbox `(75,43,904,34)`、point `(500,60)` 几何未换位；原图重算区域像素变化70.9565%，此数值不是trace自带值。没有地址栏被遮挡的证据。 / Main/review original-image inspection found selected about:blank with a white background/blue outline in the source and a gray Tampermonkey update URL in the current frame. The bbox/point geometry stayed in place. The 70.9565% changed-pixel ratio was recomputed from original images, not emitted by the trace. There is no evidence that the address field was occluded.

原run正常cancel、owned close与host cleanup均成功；取消覆盖探针未到达，`cancel_verified=false`保留。profile/extensions/cache保留，正常收尾不改写首败。 / Original-run cancellation, owned-window close and host cleanup all succeeded. The cancellation-coverage probe was not reached and `cancel_verified=false` remains. Profile, extensions and cache were preserved; cleanup does not replace the first failure.

### Runtime invariant and correction status / 运行时不变量与修复状态

1. **Failure / 故障：** R1源码以区域变化比 `>0.02` 在Decision前阻断；没有输入或Decision派发。 / R1's source pixel-change gate blocked before Decision; neither input nor Decision was dispatched.
2. **Root invariant / 根不变量：** 内容/焦点样式变化不能单独证明同几何字段已不可用；auto Choice须判断有绑定的当前帧，派发只接受该帧/候选的有效assessment。身份/几何/点位硬门禁独立保留。 / Content/focus-style variation alone does not establish that a geometrically unchanged field is unusable. Auto Choice must assess the bound current frame, and dispatch must require that frame/candidate's valid assessment; identity/geometry/point gates remain independent.
3. **Fix location / 修复位置：** Core源码修复及离线验证已完成，S1已取得单项输入证据，但整套首次失败保留。既有活跃auto Choice原请求对当前标点图审核原候选；pending不能直接dispatch，须认证scope/frame/candidate/identity并检查deadline/cancel后才claim。没有可用Choice时，区域变化 `>0.02` 仍按原规则拒绝；不新增API调用、capture、等待或重试。 / The Core correction and offline verification are complete; S1 provides single-input evidence while its first whole attempt remains failed. The existing active auto Choice request assesses the original candidate on the current marked image. Pending work cannot dispatch directly: scope/frame/candidate/identity binding and deadline/cancellation checks must pass before claim. Without usable Choice, the original `>0.02` region-change rejection remains. No API call, capture, delay or retry is added.
4. **Why not app-only / 非应用专修：** 这是共享grounding候选到派发的当前帧审核合同，适用于地址栏、搜索框及其他可变内容字段，不为Rust网站或某扩展加例外。 / This is the shared current-frame review contract between grounding and dispatch, applicable to address bars, search fields and other changing fields, without a Rust-site or extension exemption.
5. **Regression / 回归：** Main五模块105 passed in 7.01s（`test_agent_grounding_choice_revalidation.py`、`test_agent_grounding_target.py`、`test_action_review_route.py`、`test_execution_decision_check.py`、`test_visual_input_flow_contract.py`；`agent-grounding-choice-main.xml`）；worker六模块77 passed in 2.77s（`agent-grounding-choice-regression.xml`）。两组重叠，不累加。冻结 `app/core/agent_grounding_target.py` SHA-256：`44676c400cb80a7c2a9cda9a84727a0c107577ff269affdf19a4ef6d621a4416`。 / Main passed 105 checks across five modules in 7.01s; the worker passed 77 across six modules in 2.77s. Groups overlap and are not summed. The frozen Core file hash is recorded above. 70.9565%仍仅为原图诊断重算，不是trace值、通过结果或新阈值。 / The recomputed 70.9565% remains an original-image diagnostic, not a trace value, passing result or new threshold.
6. **Safety / 安全：** 有效scope、同帧同候选认证及原身份/几何门禁必须同时成立；noDecision/legacy不放宽，未知仍停交Main，不重试输入。 / Valid scope, exact-frame/candidate authentication and original identity/geometry gates must all hold. No-Decision/legacy stays unchanged; unknowns stop for Main without input replay.

原件：`D:/AgentReviewAcceptance/execution-012-rust-docs-01/flow-summary.json`、`round-1.response.json`、`round-1.host-status.json`、`failure-cancel.response.json`、`owned-cleanup.json`、`host-cleanup.json`；会话 `runtime/session-03a6f584808b4c979ab7b862aad4a2e2`。原证据未改。 / Original evidence is unchanged.

P1/R1/N1/E1/Z1/S1首次失败全部保留。共享候选源码及离线验证完成；不同的新MDN流程尚未运行。执行0.1.2未发布、build03未构建，安装及同冻结候选独立验收待完成，学习包不更新。 / Preserve all P1/R1/N1/E1/Z1/S1 first failures. Shared candidate source and offline checks are complete; the different fresh MDN flow has not run. Execution 0.1.2 is unpublished and build03 is not built; installed and independent same-candidate acceptance remain pending and learning is unchanged.


## 2026-10-13 Python docs P1 first whole attempt / Python docs P1首次整体验收

Python docs P1（`execution-012-python-docs-01`）首次整套**未通过**，0完整round：`open_python_docs` 输入与Enter已完成，Python文档位于后台标签；Main核对原图，前台为猫抓扩展欢迎页并有迅雷扩展通知。当前页面不满足文档条件，Choice `condition_not_met`（0.76，confidence 0.64）正确，不是误拒。Decision共3请求，无自动重试。 / Python docs P1 **failed its first whole attempt**, with zero complete rounds. `open_python_docs` completed input and Enter, while Python documentation was in a background tab. Main's original-image review found the foreground 猫抓 (Cat Catch) extension welcome page and a 迅雷 (Xunlei) extension notification. The current page did not meet the docs condition, so Choice correctly returned `condition_not_met` (0.76, confidence 0.64), not a false rejection. Three Decision requests were used, with no automatic retry.

原run取消结算成功，owned窗口和host正常关闭，profile/cache/extensions均保留。独立取消覆盖探针未达到，`cancel_verified=false` 不改为通过；`flow-summary.json` 保留 `passed=false`、`rounds_completed=0`、`normal_round_not_completed`，以及最终 `window_closed=true`、`cleanup_verified=true`。 / The original run's cancellation settled and the owned window/host closed normally, preserving profile, cache and extensions. The separate cancellation-coverage probe was not reached, so `cancel_verified=false` remains unchanged. The summary retains failure, zero rounds and `normal_round_not_completed`, alongside final verified window/host cleanup.

证据：`D:/AgentReviewAcceptance/execution-012-python-docs-01/flow-summary.json`、`round-1.response.json`、`round-1.host-status.json`。host-status为收尾前快照（host_alive=true、cleanup_verified=false、Decision used=3）；最终收尾以flow-summary为准，不能混淆时点。原件未改。 / The host-status file is a pre-cleanup snapshot with a live host, unverified cleanup and three Decision requests. Final cleanup is established by the later flow summary; these timestamps are distinct. Original evidence is unchanged.

这些首次失败保持原记录；当前修复与后续验收计划见上方R1检查点。 / These first failures remain unchanged; the current correction and next acceptance plan is recorded above under R1.


## 2026-10-13 Decision 当前结果与用量探针 / Current-result Decision and usage probe

普通单次左键结果核验现仅问本步当前 `condition`。原始完成回执认证后，`step_result_check` / `decision_executed_click_annotation.v3` 上传一张当前整图，仅标真实历史点击点与刻度，不按旧候选 bbox 裁结果图、不伪装成字段核验。Choice 只接收必要尺寸、历史点及适用的 ROI 映射；原 receipt SHA、身份、几何、截图、完整请求和账本认证留在本地。历史点不证明当前结果。 / Ordinary single-left-click result checks now ask only the current `condition`. Authenticated completed receipts use `step_result_check` / `decision_executed_click_annotation.v3` with one current full frame marked only by the actual historical point and ticks, without stale-box cropping or a field-check disguise. Choice receives compact dimensions, point and applicable ROI mapping; receipt hashes, identity, geometry, capture, full requests and ledger authentication remain local. The historical point does not prove the current result.

字段分支、before-action、专用 native/temporal 问题及阈值不变；本轮普通点击标注不扩展 `wait_policy` 或时间序列观察，其他真实动作保持既有行为。旧保存 records 按原绑定完整认证，不静默采用改变后的证据。 / Field, before-action and dedicated native/temporal semantics and thresholds remain unchanged. This ordinary-click slice does not expand `wait_policy` or temporal observations; other genuine actions retain existing behavior. Saved legacy records keep their original authenticated bindings without silently adopting changed evidence.

真实摘要：`D:/AgentReviewAcceptance/decision-usage-probe-01/summary.json`。8/8请求完成，`authorizes_action=false`、`adopted=false`、`automatic_retry_allowed=false`，0桌面动作。每对使用同一保留原图；普通新路线加真实历史点标注，字段两图SHA/尺寸完全相同。 / All eight calls completed without action authority, adoption, automatic retry or desktop activity. Each pair uses the same retained source image; the new ordinary route adds the actual historical-point mark, while both field uploads have identical image hashes/dimensions.

| Case / 条件 | Old label / 旧 | New label / 新 | Input tokens old→new | HTTP ms old→new |
| --- | --- | --- | --- | --- |
| Visible round-two text / 第二轮文字 | condition_met | condition_met | 1550→1484 | 1466.4518→275.2627 |
| Wrong round-one text / 错误第一轮文字 | condition_not_met | condition_not_met | 1548→1482 | 189.4294→167.0900 |
| Original title marker / 原标题条件 | evidence_insufficient | evidence_insufficient | 1559→1493 | 207.6592→163.0820 |
| Field round-two value / 字段第二轮值 | condition_met | condition_met | 1999→1533 | 170.1750→162.5953 |

8次保留图真实API全部符合预设labels，旧新均正确分类，不证明准确率提升。字段同图 input tokens `1999→1533`（−23.3%）；普通结果三对各减少66 tokens（约4.2%）。新请求HTTP `162.5953–275.2627ms`；首个旧请求 `1466.4518ms` 含连接/服务端波动，不能宣称5倍提速。0桌面动作、未采用结果、无自动重试、阈值不变。 / All eight retained-image live calls matched preset labels in both arms, not evidence of an accuracy gain. The identical field image used `1999→1533` input tokens (23.3% fewer); three ordinary pairs each saved 66 tokens (about 4.2%). New HTTP times were `162.5953–275.2627ms`; the first old `1466.4518ms` includes connection/server variation, not a fivefold speedup. No desktop actions, result adoption, automatic retries or threshold changes occurred.

普通标注PNG使三对完整wire字节增加，token减少不代表传输字节也减少。标注不能补齐缺失标题栏，也不将N1末步改记通过。 / Annotated ordinary PNGs increase total wire bytes in those three pairs; fewer tokens do not imply fewer transmitted bytes. Annotation cannot restore the missing title bar or turn N1's final step into a pass.

Main 离线组179（provider）、118（specialized）、112（binding）、最终两模块48项均通过；worker另组187通过。各组重叠，不相加为唯一总数。 / Main passed groups of 179 provider, 118 specialized, 112 binding and final 48 two-module checks; a worker separately passed 187. Groups overlap and are not summed as a unique total.

这些首次失败保持原记录；当前修复与后续验收计划见上方R1检查点。 / These first failures remain unchanged; the current correction and next acceptance plan is recorded above under R1.


## 2026-10-13 Notepad first whole attempt / Notepad 首次整体验收

Notepad N1 首次整体验收 `execution-012-notepad-01` **未通过**：首轮三步自动完成；第二轮文档替换、打开 File 菜单和 Save 均已派发，磁盘最终内容与预期 UTF-8 字节完全一致，但最后 Choice 返回 `evidence_insufficient` 0.58（`condition_met` 0.33、`condition_not_met` 0.09），原 run 未完成。取消环节未到达，不计取消通过。 / Notepad N1 did **not pass its first whole acceptance attempt**. Round 1 completed all three steps automatically. Round 2 dispatched replacement, File-menu opening and Save, and final disk bytes exactly matched the expected UTF-8 content; final Choice nevertheless returned `evidence_insufficient` 0.58 (met 0.33, unmet 0.09), leaving the original run incomplete. Cancellation was not reached or verified.

Save 条件要求标题没有未保存标记，实际 1065×976 原图从 File 菜单开始，仅含客户区及菜单，不含标题栏；`full-window` 文件名不代表 OS 整窗。可确认条件与已给图之间有证据范围缺口，不能据此推断模型内部原因、认定保存失败或宣称 Decision 误拒。 / The Save condition required no unsaved title marker, while the 1065×976 image starts at the File menu and contains the client surface plus menu, without the caption. The `full-window` filename does not establish OS-whole-window coverage. This confirms an evidence-scope gap, not the model's internal reason, a failed save or a false Decision rejection.

原 `flow-summary.json` 保留 `passed=false`、`rounds_completed=1`、`cancel_verified=false`、`normal_round_not_completed`，以及当时 `window_closed=false`。随后 Main 的 `main-owned-window-cleanup.json` 确认 `window_closed=true`、`forced=false`、`files_preserved=true`；宿主摘要 `cleanup_verified=true`。正常收尾不改写首次失败。 / The original flow summary retains failure, one completed round, unverified cancellation, `normal_round_not_completed` and the then-open window. Main's separate later cleanup record confirms normal owned-window closure without force and preserved files; host cleanup was verified. Cleanup does not replace the first failure.

Evidence / 证据：`D:/AgentReviewAcceptance/execution-012-notepad-01/flow-summary.json`、`document-final.json`、`main-owned-window-cleanup.json`；原会话 `runtime/session-d3824391f581416f9b55d56bf2689978`，Save 原始回执 `runtime-output/local-direct-steps/local-step-6832a6b5b9844ef5a09a4a27f91b4a10/report.json`，最终 Choice `task-plan-decisions/trial-exec-dd406576b60a0d1667a47f20ea407f90.json`。这些原件未修改。 / Original evidence remains unchanged.

本段保留N1首次失败事实；后续源码与保留图对照见上方检查点。Python docs P1亦首次失败且正常收尾；下一不同新流程待准备，执行0.1.2未发布、学习包不更新。 / This section retains the N1 first failure; subsequent source and retained-image evidence is recorded above. Python docs P1 also failed its first attempt and closed normally. A different new workflow remains to be prepared; Execution 0.1.2 is unpublished and learning is unchanged.

## Earlier checkpoints (original records retained) / 前序检查点（原记录保留）

Private cancellation-driver repair is now verified offline against the original 7-Zip evidence: the real zero-input wait is accepted, six altered copies are rejected, the beta suffix is absent, and original evidence/first-failure hashes are unchanged. Main reran this check successfully with zero desktop/API calls. This is targeted regression only; the 7-Zip first attempt remains failed. Next acceptance uses a different fresh Explorer workflow. / 私有取消断言已按真实零输入合同修复：Main 离线回放原证据通过，6个变造副本被拒绝、后续 beta 未入队、原证据及首次失败摘要哈希不变，桌面/API调用均为0。这只计针对性回归，7-Zip首验仍未通过；下次改用新的文件资源管理器流程。

Status: preparation in progress; not published. The first 7-Zip acceptance did not pass as a whole; a different new real workflow is required after the private cancellation assertion is fixed and verified offline. / 发布准备中，尚未发布。7-Zip 整套首验未通过；修复私有取消断言并离线验证后，须换不同新真实流程首验。

## Current acceptance criterion / 当前验收标准

用户最新验收标准：新真实流程必须在首次尝试无错误完成整套验收（业务步骤、同会话连续使用、取消及正常收尾）。若首次未完整通过，保留首败，修复并完成相关离线回归后，换一个不同的新真实流程继续，直到出现首次完整通过；同一失败流程的成功复测只能记为回归，不能替代该标准。原有安全门禁不放宽。 / Latest user criterion: a fresh real workflow must complete its entire first acceptance attempt without error, including business steps, repeated same-session use, cancellation and normal closure. If it does not, preserve the first failure, fix and verify the relevant path offline, then switch to a different fresh real workflow until one passes completely on its first attempt. A successful rerun of the failed workflow is regression evidence, not a substitute for this criterion. Existing safety gates remain effective.

## Scope / 范围

Execution only: version 0.1.2, intended tag instant-v0.1.2. Learning stays at 0.1.0-preview.3; no learning installer is rebuilt or uploaded. The execution installation identity remains compatible with preview upgrades, with stable display names. / 仅更新执行，学习安装器不变；执行保留原升级身份。

OpenAI Decisions API Choice with gpt-6-luna, current-step evidence, cropped click annotations, default visual replacement and the narrow NVIDIA overlay exemption are the focus. The upstream API remains public beta as verified on 2026-10-12. / 发布重点为 Choice、当前步骤证据、点击裁剪图、默认视觉替换及精确录屏白名单。

## Existing source evidence / 已有源码证据

- [Default replacement](DEFAULT_REPLACE_20261012.md): 591 offline cases passed.
- [Recording overlay](RECORDING_OVERLAY_ALLOWLIST_20261012.md): 237 offline cases passed; the missed-region first failure, user-interrupted rerun and final automatic 3/3 success are separate records.
- Counts overlap. These source results do not certify the new installer or consecutive stability. / 用例重叠；源码结果不转计新安装包及连续稳定性。

## Release acceptance / 本次验收

- Source regressions: 3,718 passed, one skipped, one stale test assertion failed. The assertion still expected the removed selection review; production was unchanged. The affected rerun passed 40 cases (one expensive payload case deselected). / 源码回归首次 3,718 通过、1 跳过、1 条旧断言失败；修正旧的全选后审核断言后，相关 40 条通过。
- Packaging regressions: 48 passed, one full payload build deselected; the real build was performed separately. / 打包回归 48 通过，真实载荷另行构建。
- Build 01 passed isolated dependency and install checks, but the installed acceptance driver could not import the maintained startup helper. No browser input or API call occurred in that attempt. Adding the helper to the package entry list passed a red/green regression plus startup checks: 12 passed. Build 01 is superseded. / 首包漏收维护启动辅助模块，已以红绿回归修复，首次失败保留。
- Build 02: 606 source-freeze entries, 604 payload files; isolated input entrypoints and installed hashes passed. Setup SHA-256: 89cd900c687e3cedd257928eeb99bc4b7d6f810167ff7fe7fa4f1a601752bdd2. Learning was not rebuilt. / 第二包依赖、安装摘要核验通过，未构建学习包。
- Main installed runs stable-main-02 and stable-main-03 each completed the first Google → java → first ordinary result round (3/3). Both second rounds failed before Enter because the Google URL was not entered. Decision returned condition_not_met correctly; both hosts cleaned up successfully and the payload hashes stayed unchanged. These are **not** two consecutive automatic successes. / 两次连续验收均首轮 3/3 成功、第二轮输入失败；Decision 正确阻止回车，宿主收尾成功。不得记成连续自动成功。
- Both failing click traces show an Edge translation bubble before dispatch; afterward the bubble is gone but the address bar is not editing, then Ctrl+A selects the page. Actual mouse coordinates and window identity match. Whether activation or the click consumed dismissal remains under investigation. The user's observation that the browser seemed stuck is preserved separately; it is not treated as proof of manual interference. / 两次均出现翻译气泡收起而地址栏未进入编辑，实际坐标与窗口匹配；继续定位激活与点击的影响，不归因为用户干扰。

Pending: narrow failure diagnosis, required continuous acceptance, independent frozen-candidate acceptance, owned test installation cleanup, publication and public-download hashes. Stable release remains blocked by the repeated consecutive-use failure. / 待完成单点诊断、连续验收、独立验收、测试安装清理及发布；重复失败未闭合前不发布正式版。

No general accuracy or speed gain is claimed. The persistent test browser profile/cache is retained. / 不宣称通用准确率或速度收益，测试浏览器资料与缓存保留。

## Follow-up correction / 后续修正

The narrow diagnostics reproduced a difference after repeated window selection. A foreground-idempotence guard passed 32 offline checks, but the patched live diagnostic still did not demonstrate address-bar editing. It is not a verified fix for the consecutive-run failure. / 重复选窗相关单点诊断后增加前台幂等检查，离线32项通过，但修正后实机仍未证明地址栏进入编辑；不能宣称连续故障修复。

The user redirected the fix to a continuous click-and-replace action and explicitly deferred click-consumption confirmation. Implement the existing target gate → click + select all + replace → text-only result check, without an intervening Decision request, screenshot or activation. Source implementation and regression are in progress; no new installer has been built. / 用户将修正收敛为连续点击替换，并明确暂不确认点击是否被弹层吞掉；源码及回归开发中，未构建新安装包。


## Continuous input source check / 连续输入源码检查

The default visual path now binds click, select-all and paste in one maintained action. Main's 36-module regression finished with 823 passed (34.93s), after preserving the first 812-pass/11-failure fixture run and its repair. No intervening click-consumption, focus-appearance or empty-field Decision was added. / 默认视觉路径已将点击、全选和粘贴绑定为一次维护动作。Main 36模块回归823项通过；首次812通过、11条历史夹具失败及修正记录保留，未增加吞点击、焦点外观或空框判断。

The first source live run (`compound-main-01`) visibly entered the correct Google URL, but the new value-proof receipt validator returned `visual_compound_receipt_binding_invalid` before the text Decision request. No Enter was dispatched; the host cleaned up, the frozen source stayed unchanged and the retained browser profile was not cleared. This is a source integration failure, not a Decision false rejection or a successful full round. A minimal receipt regression and repair are in progress; no new installer has been built. / 首次源码实测已正确输入网址，但新值证明的回执绑定校验在文字Decision之前失败；未回车，宿主已收尾，源码冻结未变，资料目录未清理。这是源码衔接故障，不记为Decision误拒或完整轮成功；正在补最小回执回归修复，尚未构建新包。


## Enter timing experiment — reverted / Enter 时序对照已回退

The user-requested 200 ms pause between text-value adoption and Enter authorization was tested with the retained independent Edge profile. Main's offline checks passed (37 tests). The first live three-step round completed; the second stopped at text-value checking because the address bar still showed the Java URL. Enter was not issued in that second round. Thus the experiment did not establish a continuous-use fix or isolate the earlier Enter/navigation failure. A passive observer recorded the first round's Ctrl+A / Ctrl+V / Enter and the second round's Ctrl+A / Ctrl+V; it does not prove application consumption.

At the user's request the 200 ms change was **fully reverted**, including its experiment-only source tests (archived privately with the evidence). The `app/execution/input_sequence.py` SHA-256 is `20a479843fe46950d8fec6fb8264f93a6649a0612fc856c5a3c5d21e15f31924`, matching its entry in `compound-source-manifest-02.json` (the pre-experiment compound-source freeze, not installer build 02). Main ran the existing Enter-preparation and visual-flow contract modules after rollback: **35 passed**. No threshold or profile/cache changes were made. The source candidate remains unreleased. The failure root cause is still under investigation; screenshots show a translation prompt before the second round and its disappearance afterward, which is a lead rather than a confirmed swallowed-click diagnosis.

按用户要求，以保留的独立 Edge 资料目录实测文字核验与 Enter 之间的 200 毫秒间隔。离线 37 项通过；第一轮完整三步通过，第二轮输入后仍为 Java 网址，文字核验拒绝且未发送 Enter。该对照没有证明连续使用问题已修复，也没有隔离先前的 Enter 跳转问题。只读按键观察记录了第一轮 Ctrl+A / Ctrl+V / Enter、第二轮 Ctrl+A / Ctrl+V，不能据此证明应用已消费输入。

用户要求无效即回退，现已**完整移除该等待**，相关实验测试仅归档到本地证据。`app/execution/input_sequence.py` 的 SHA-256 恢复为 `20a479843fe46950d8fec6fb8264f93a6649a0612fc856c5a3c5d21e15f31924`，与 `compound-source-manifest-02.json` 对应项一致（指实验前组合源码冻结，不是安装器 build02）；Main 在回退后运行既有 Enter 准备与视觉流程契约，**35 项通过**。阈值、资料目录和缓存未改，候选未发布。第二轮前出现翻译提示框、输入后消失，是后续排查线索，尚不能当作点击被吞的结论。


## Input-candidate feasibility clarification / 输入候选可行性补充

The current provider adds the following clarification only for candidate Choice whose original action is `input_sequence`:

> This click starts text input. Can it directly reach the target without first handling an interactive popup? If a visible interactive popup must be handled first, or this click would only dismiss it, the current action cannot proceed.

当前 provider 仅对原动作为 `input_sequence` 的候选 Choice 补充上述说明。本次点击将开始文字输入：能否不先处理交互弹窗就直接到达目标？若可见交互弹窗必须先处理，或本次点击只会关闭它，则当前动作不能继续。

The original condition, source report and thresholds stay unchanged. This uses one request and the same single marked candidate image. Ordinary click and predicate paths do not receive the addition. No post-click focus-style or click-consumption confirmation is introduced; compound click/select-all/replacement and the text-only value check remain unchanged. / 原条件、来源报告和阈值不变，仍为一次请求、同一张候选标注图；普通 click 与 predicate 不添加此说明。不增加点击后焦点外观或吞点击确认，连续点击替换和输入后只比文字保持不变。

| Retained image / 保留原图 | Baseline | Proposed clarification / 补充版 |
|---|---|---|
| `popup-input-02`: visible translation popup / 可见翻译弹层 | `condition_met` | `condition_not_met` |
| `popup-input-03`: no popup / 无弹层 | `condition_met` | `condition_met` |

These were four diagnostic API requests over two retained images, with no desktop input or execution authority. The production request bodies then matched both frozen proposed bodies exactly in a zero-API parity check, including the same single marked image and unchanged original condition/source report. Private evidence retained locally: `candidate-feasibility-probe/results.json` (two images/four diagnostic calls) and `candidate-feasibility-probe/production-wire-parity.json` (two matching bodies/zero API calls). / 两张保留原图共四次诊断 API 请求，无桌面输入及执行授权。随后零 API 的生产请求体一致性检查确认两案均与冻结补充版完全一致，仍为同一单张标注图，原条件和来源报告未改；原始证据以所列私有文件名本地留存，不作为公开下载链接。

Main independently ran 9 related modules: **186 passed in 8.33s**, with no failures or skips (private evidence `input-feasibility-main.xml`; suite timing 8.315s). These checks are not additive with earlier overlapping counts. / Main 独立运行相关 9 模块，**186 项通过，pytest 摘要 8.33s**，无失败/跳过（XML suite 计时 8.315s）；与前序重叠集合不累加。

At this diagnostic checkpoint, this was a two-sample prompt comparison and offline regression, not new-candidate live acceptance or proof of a complete browser root cause. The new candidate remains unreleased, required continuous/installed acceptance is pending, and the earlier failures stay recorded. The ineffective 200 ms experiment remains reverted; browser profile/cache and thresholds are unchanged. / 在本诊断检查点，以上仅为两样本提示词对照及离线回归，不代表新候选实测通过或浏览器根因已完整确定。新候选未发布，连续与安装验收尚未完成，首次失败继续保留；无效的 200ms 实验保持回退，资料目录、缓存和阈值不变。


## New-candidate source observation / 新候选源码观察

Main ran the new candidate at `D:/AgentReviewAcceptance/native-focus-geometry-20261012-input-feasibility-01`, session `session-ecd7416f5c024a1eb07d5af7dbc9a056`. Round 1 completed `google`, `search_java` and `open_first` (3/3). In round 2, the Google candidate's before-action Choice returned `condition_not_met` for the visible translation popup, with `action_executed=false` and no Ctrl+A, Ctrl+V or Enter. Main inspected the image and confirmed the popup; before/after images share SHA-256 `c8969544da51ca47d0d2132431cf5075e04418de55c29a70ac96d6be0cff0e2f`. Host cleanup was verified. / Main 在上述新数据根和会话实测：第一轮三步完成；第二轮 Google 候选在动作前因可见翻译弹层返回不满足，零输入，未发送全选、粘贴或 Enter。Main 已检图确认弹层，前后图同上述 SHA，宿主清理成功。

This is one complete round plus a controlled pre-dispatch refusal, **not two automatic successful rounds**. It supports the current popup feasibility behavior without proving the complete cause of earlier input/navigation failures. Formal recover/resume validation in a new retained session was still in progress at this checkpoint; no recovery result is claimed here. Installed/independent acceptance and publication remain pending, and browser profile/cache is retained. / 这是一次完整轮加一次受控派发前拒绝，**不是两轮自动通过**；支持当前弹层可行性判断，但不证明旧输入/跳转失败的完整根因。本检查点新的保持会话正式 recover/resume 验收尚在进行，不记录恢复成功；安装、独立验收与发布仍待完成，资料目录及缓存保留。


## Formal recovery acceptance / 正式恢复验收

Main subsequently exercised the maintained `recover` → `resume_pre_dispatch` path at `D:/AgentReviewAcceptance/native-focus-geometry-20261012-input-recovery-01`, in the same `session-60c510f9d79a43638c2ff4b277698094` across both rounds. Each initial run was `blocked_before_dispatch` with `action_executed=false` and no input. Main used formal recovery to dismiss the visible translation popup, then resumed that original run; `google`, `search_java` and `open_first` each completed (3/3 per round). / Main 随后在上述新数据根、同一会话完成两轮正式 `recover` → `resume_pre_dispatch` 验收。两轮原 run 均先在派发前零输入阻断；Main 经正式恢复关闭可见翻译弹层，再续原 run，各三步完成。

Each round required **one Main intervention** (`dismiss-translation-01` and `dismiss-translation-02`). The retained `recovery-summary.json` records both rounds as completed, `same_run=true`, `initial_state=review_required`, `initial_action_executed=false` and `unattended_two_round_pass=false`. This is **recovery success with Main intervention, not unattended two-round success**. / 两轮分别需要 **一次 Main 介入**；上述恢复摘要保留两轮完成、同一原 run、初始待审核且零动作、非无人干预通过等原始字段。这是 **有 Main 介入的恢复通过，不是无人干预两轮通过**。

Main verified host cleanup and normal closure of the original owned browser (owner run `compound-main-01`, `isolated-browser-cleanup.json`): `profile_preserved=true`, without forced termination. The retained browser profile/cache was not deleted or reset. The source was frozen as `compound-source-manifest-05.json`, containing 591 entries and excluding the eight documentation files concurrently updated here. No added Enter delay or threshold change was introduced. / Main 已核对宿主收尾及原 owned browser 的正常关闭，证据归属 `compound-main-01` 的收尾记录；资料目录保留、未强制终止、未删除或重置缓存。源码 manifest05 冻结 591 项，排除本轮并行更新的八份文档；未增加 Enter 间隔、未改阈值。

The earlier E2 failure—text accepted but Enter did not navigate on the second round—remains preserved and is not fully explained by this recovery result. The popup refusal and recovery path are now evidenced for these runs; they do not establish a complete browser root cause, general reliability or installed/independent release acceptance. Execution 0.1.2 is still unpublished; learning is unchanged. / 旧 E2 第二轮文字通过、Enter 后未跳转的首败仍保留，本次恢复结果未完整解释其根因。当前证据支持这些 run 的弹层拒绝与正式恢复路径，不代表浏览器根因全部确定、通用可靠性或安装/独立发布验收完成；执行 0.1.2 仍未发布，学习版本不变。

## First 7-Zip acceptance attempt / 7-Zip 首次验收

7-Zip 首验 `D:/AgentReviewAcceptance/execution-012-7zip-01`：两轮正常业务均自动 3/3 `completed`；取消脚本却错误期望输入已经完成，实际 `always_main` 在 before-action 返回 `blocked_before_dispatch`、`action_executed=false`，因此 `flow-summary.json` 保留 `passed=false`、`cancel_verified=false` 和 `cancellation_original_input_not_completed`，整套首验不计通过。Main 随后正常关闭本轮 owned 7-Zip（`main-owned-window-cleanup.json`），宿主 `cleanup_verified=true`，测试文件前后相同；后续收尾成功不补记取消通过。 / In the first 7-Zip acceptance, both normal business rounds completed all 3 steps automatically. The cancellation driver incorrectly expected completed input; `always_main` actually stopped before dispatch with no action. The raw summary remains `passed=false` and `cancel_verified=false`, with `cancellation_original_input_not_completed`, so the whole first attempt did not pass. Main subsequently closed the owned 7-Zip window normally, host cleanup was verified and fixture files were unchanged; successful closure does not establish cancellation success.

The cancellation branch stopped at the intended `always_main` before-action gate; it had not completed input. The private driver instead asserted that original input must already be complete and raised `ValueError: cancellation_original_input_not_completed`. Cancellation was therefore not verified. This is a private acceptance-assertion failure at the actual no-input boundary, not evidence that input had been dispatched or that the cancellation journey passed. Automatic retries were zero. / 取消分支停在 `always_main` 动作前门禁，尚未完成输入；私有脚本却断言原输入已经完成并抛出上述错误。因此取消验收未完成；不能把实际零输入改记成已输入，也不能补记取消通过。自动重试为零。

The original `flow-summary.json` still records `window_closed=false`; the later `main-owned-window-cleanup.json` separately records `window_closed=true`, `forced=false` and `files_preserved=true`. `host-cleanup.json` records `cleanup_verified=true`, and the before/after fixture snapshots are equal. Keep the original summary and the follow-up closure as separate evidence. / 原 `flow-summary.json` 的 `window_closed=false` 不改写；后续 Main 关窗记录单独确认已正常关闭、未强制终止、文件保留。宿主收尾记录确认清理成功，测试文件前后快照相同；首次摘要与后续收尾证据分开保留。

私有 7-Zip 取消断言随后已按真实 before-action 零输入合同修复，Main 离线回放原证据通过：6 个变造副本被拒绝、后续 beta 未入队、原证据及首次失败摘要哈希不变，桌面/API 调用为 0。这只计针对性回归，7-Zip 首次整套验收仍未通过。 / The private 7-Zip cancellation assertion was subsequently repaired for the real before-action no-input contract. Main's offline replay accepted the original evidence, rejected six altered copies, confirmed no beta suffix and unchanged original evidence/first-failure hashes, with zero desktop/API calls. This is targeted regression only; the complete first 7-Zip attempt remains failed.

## Explorer first attempt and complete-field correction / Explorer 首败与完整字段修正

Explorer 首验位于 `D:/AgentReviewAcceptance/execution-012-explorer-01`。首轮第 1 步停止，**0 完整轮**；正常关闭本轮 owned 窗口与宿主收尾均为 true。收尾成功不改写首败，也不计两轮或完整验收通过。 / The first Explorer attempt stopped at step 1 of round 1, with **zero complete rounds**. Normal closure of the owned window and host cleanup were both true. Successful closure neither replaces the first failure nor establishes two-round or complete acceptance.

1. **Failure / 失败：** Main 核对原图确认路径实际输入正确，但 Luna 候选 bbox 仅框住右侧空白，后验 ROI 为 193×53，遗漏左侧路径文字，Choice 返回 `condition_not_met`。这次失败是字段证据范围不完整，不是实际路径未输入。 / Main confirmed the correct entered path in the original image. Luna's candidate box covered only the right-hand blank area; the 193×53 value ROI omitted the path text on the left, so Choice returned `condition_not_met`. The field evidence was incomplete.
2. **Root invariant / 根合同：** 输入字段 `bbox` 应覆盖整个可见字段及已有文字区，即使目标要求点击空白子区；`click_point` 独立选择该可点击子区，可以不居中。 / An input-field `bbox` must cover the whole visible field and existing text even when the requested click is in a blank subregion. Select `click_point` independently within that clickable subregion; it need not be centered.
3. **Fix location / 修正位置：** shared `grounding.v1` 的既有字段描述与外部 API grounding 提示词明确上述语义；没有新增协议字段或版本。 / The shared `grounding.v1` field descriptions and external API grounding prompt now state this extent/point distinction without new protocol fields or a version change.
4. **Why not app-only / 为何不是应用特例：** 地址栏、搜索框及普通输入字段的点击子区都可能小于完整值区域，后续裁剪均需完整字段框；不依赖 Explorer 名称或布局规则。 / Address bars, search boxes and ordinary fields can all have a click subregion smaller than their visible value area. Their downstream crops need the complete field box, independently of Explorer names or layout.
5. **Regression / 回归：** Main 相关 6 模块 **197 项通过**（`complete-field-main.xml`），覆盖正式请求语义、缩放后的完整字段 ROI 及非居中点击点保留；原图正确/错误文字条件对照见下。此前命令误拼了不存在的 `test_grounding_contract`，没有运行测试；`complete-field-main-command-error.xml` 单独保留，不能记为产品红测。 / Main passed **197 checks across 6 modules**, covering the production request meaning, full-field ROI after scaling and retention of an off-center click point. The retained-image correct/wrong text controls are below. An earlier command named nonexistent `test_grounding_contract` and ran no tests; its separate `complete-field-main-command-error.xml` is a command error, not a product red test.
6. **Safety / 安全影响：** 未放宽点击点、窗口身份、几何或动作门禁，未知结果仍停止交 Main；不增加 UIA、横向全屏回退、额外请求、重试或阈值调整。 / Click-point, identity, geometry and action gates are unchanged, and unknown results still stop for Main. No UIA, horizontal full-screen fallback, additional request, retry or threshold change is added.

限制：本地 48px 点框及既有 bbox 中心路线未改，本次证据不声称覆盖或修复这些路线。 / Limitation: the local 48px point box and existing bbox-center route are unchanged and are not claimed covered or fixed.

### Read-only retained-image API probe / 保留原图只读 API 探针

第一次 `complete-field-probe` 发出 1 grounding 与 1 Decision；私有 probe payload 缺少 `request_sha256`，Decision 返回后未保存结论。该诊断程序错误保留，不把它记成有效判断结果。修复私有 probe 后，`complete-field-probe-02` 复用已有 grounding，仅再发出 2 次 Decision，没有桌面动作。 / The initial probe issued 1 grounding and 1 Decision call. Its private payload omitted `request_sha256`, so no conclusion was saved after the Decision response. This diagnostic-program error remains recorded and is not counted as a valid judgment. After repairing the private probe, probe 02 reused that grounding and issued only 2 further Decision calls, with no desktop actions.

新的完整字段 bbox 为 `(106, 171, 763, 23)`，原实际点击点 `(776, 182)` 保留不变。Main 已检查正式上传的裁剪图，确认包含完整路径。 / The new full-field bbox is `(106, 171, 763, 23)`; the original actual click point `(776, 182)` is unchanged. Main inspected the actual uploaded crop and confirmed that it contains the complete path.

| 文字条件 / Text condition | Choice result | Selected-choice probability | HTTP ms |
|---|---|---:|---:|
| 正确 / Correct | `condition_met` | 0.90 | 434.6255 |
| 错误 / Wrong | `condition_not_met` | 1.00 | 149.9281 |

两次 probe 共 **4 次 API（1 grounding + 3 Decision）、0 桌面动作**。这些回放仅为诊断，不产生执行授权；两项文字对照及耗时不构成通用准确率或速度 benchmark，也不把 Explorer 首验改记通过。 / Across both probes there were **4 API calls (1 grounding + 3 Decision) and zero desktop actions**. These replays are diagnostic and grant no execution authority. The two text controls and their timings are not a general accuracy or speed benchmark and do not turn the Explorer first attempt into a pass.

下一真实验收改用不同的全新 Notepad 文档输入→File→Save 流程，包含同会话两轮、取消及正常收尾。用户标准仍为首次整套无错误才通过；失败后的修复或旧流程复测只作回归。执行 0.1.2 未发布，学习安装器、浏览器资料/缓存与阈值不变。 / The next real acceptance uses a different fresh Notepad document input→File→Save flow, including two rounds in one session, cancellation and normal closure. The user's criterion still requires the entire first attempt to pass without error; repair checks or reruns of a failed flow are regression only. Execution 0.1.2 remains unpublished, with learning, browser data/cache and thresholds unchanged.

## Fresh source acceptance after correction / 请求修正后的新流程源码验收

Frozen manifest20 (609 collected files) completed Bing → search `MDN JavaScript Array map` → open the first ordinary MDN Array.prototype.map article on its first full attempt: two rounds in one window/session, authenticated zero-input cancellation, normal owned-window/host cleanup, zero Main repair/retry, unchanged source and retained browser profile/cache. The previous installed Earth failure is still a failure, not relabeled. / manifest20 全新MDN流程首次整套两轮、零输入取消和正常关闭通过；无主Agent修补或重试，源码未变、缓存保留。旧安装版地球流程失败仍保留。

20 Decision requests used 23,176 input tokens; the four field-value requests used 458–547 tokens and 166.822–280.181 ms HTTP (median179.419ms). Seven separate grounding calls include the cancellation probe. These are observed request figures, not complete-task comparative timing. Rebuilt installed and independent acceptance remain pending at this source freeze. / Decision20次、23,176输入tokens；字段4次458–547tokens，HTTP约167–280ms、中位179ms；另7次定位含取消。不是任务总耗时或前后对照，重建安装及独立验收在此冻结时待完成。

## Candidate04 installed first attempt / 候选04安装版首次尝试

The source MDN evidence at `D:/AgentReviewAcceptance/execution-012-bing-mdn-01/flow-summary.json` records `passed=true`, two completed rounds, authenticated zero-input cancellation, normal owned-window/host cleanup, zero automatic retries and a retained profile. The separate installed attempt at `D:/AgentReviewAcceptance/execution-012-bing-mdn-installed-main-01/flow-summary.json` records `passed=false`, `rounds_completed=0`, `cancel_verified=false` and zero automatic retries. It reached round one's `search_mdn_map`, where dark `MDN JavaScript Array map` was entered and gray inline `guide` remained an unaccepted `Tab` suggestion. The production Choice returned `condition_not_met` for the correct value (probability 0.76), so Enter was not dispatched. The owned window and host closed normally; source hashes and the isolated browser profile were preserved. This is the installed first failure, not a completed continuous-use run. / 源码 MDN 摘要记录首次整套通过、两轮、零输入取消、正常收尾与零自动重试。独立的安装版首次摘要记录失败、零完整轮次、取消未验证；首轮 `search_mdn_map` 中深色 `MDN JavaScript Array map` 已输入，灰色内联 `guide` 仍是待按 `Tab` 接受的建议。正式 Choice 以 0.76 将正确值判为不满足，Enter 未派发。owned 窗口与宿主正常关闭，源码哈希和隔离浏览器资料均保留；这次不计连续使用通过。

Retained-image diagnostics are at `.superpowers/sdd/2026-10-12-execution-stable/mdn-inline-suggestion-probe/results.json`, `mdn-inline-suggestion-probe-02/results.json` and `mdn-inline-suggestion-probe-03/results.json`. The original question rejected the correct entered value and falsely accepted a wrong expected value containing `guide` (0.99 met). Added exclusion wording still failed; revised wording with full/tight crops passed the positive value but falsely passed the suggestion counterexample (0.94/0.81 met). Stronger option descriptions still failed to classify both at once: the full crop accepted the suggestion and rejected the correct value; the tight crop rejected both. These three diagnostic variants were not adopted or counted as a repair. A common, verified distinction between committed text and unaccepted inline suggestions is still required before repeating source and installed continuous acceptance. Execution 0.1.2 remains unpublished and has not passed independent live acceptance. / 保留图三组诊断分别见上述 `results.json`：原问法误拒正确值、却以 0.99 误过含 `guide` 的错误期望；补充排除提示仍失败；改问法与完整／紧裁图让正例通过，反例仍以 0.94／0.81 误过；进一步收紧选项说明后，完整图仍误过反例并误拒正例，紧裁图则同时拒绝正反例。均未采纳或计作修复。必须先建立并验证已输入文字与未接受内联建议的通用区分，再重做源码及安装版连续验收；执行 0.1.2 未发布，也未通过独立实机验收。

### Current inline-completion evidence / 当前内联补全证据

Candidate04 did not pass installed acceptance: the typed value `MDN JavaScript Array map` was rejected while the unaccepted gray suffix `guide` could be incorrectly treated as entered. Boundary prompts and folded crops did not fix both cases and were not adopted. The maintained complete annotated ROI stays unchanged. The field-only Choice now asks for Main review when a gray suggested suffix with an acceptance-key hint is visible; ordinary text comparison remains one question/request with its expected literal in the question. No threshold, wait, retry, focus/UIA check, or browser-profile setting changed.

候选04安装验收失败，未发布。生产请求明确把“灰色建议后缀＋接受键提示”交回 Main，不宣称能正确区分其已输入边界；保留完整裁剪标注、不增加请求。最终选定样本：普通字段6组正反例12/12分类正确；同一灰色建议图的3个期望都转 Main（这是接管策略验证，不是3次识字正确）。HTTP约126–258ms，424–597输入tokens；离线9文件243通过。此前宽泛描述误转普通URL、边界/折行方案失败均保留且未采用。新鲜流程及安装验收尚待完成。

### Annotation occlusion and new-flow results / 标注遮字与新流程结果

SQLite source attempt completed both input/search steps, then correctly stopped without clicking: ordinary result links were outside the visible viewport, occupied by Bing summary cards. The unchanged two-round plan lacked a scroll/replan step; the attempt remains incomplete. DuckDuckGo→Rust completed its first three-step round, then stopped in round two after the correct `Rust ownership book` entry: the rendered historical-click ring covered the final letter. No Enter followed; normal owned-window/host cleanup and profile retention passed in both attempts.

通用证据约束：派生标注不能盖住本次要读取的文字。新字段值展示在安全2倍大小范围内，完整原ROI放大后添加外沿坐标刻度，字段内部不画圆环；点击前目标审核不变。不添加 API 或等待，不调整阈值。真实失败图及6组保留字段共14个正反例分类正确，另3个灰色补全样本按声明策略交 Main。每例仍一张图/一个请求，输入377–597tokens；17次HTTP为130–1033ms（中位数约166ms），含一次首请求长尾。该选定样本结果不代表普遍准确率。超尺寸字段保留原显示路线，不宣称其标记布局已改变。后续用全新argparse流程验证，未发布。

### Fresh argparse source acceptance / argparse 全新源码验收

2026-10-13: DuckDuckGo → search `Python argparse documentation` → open the ordinary official Python argparse result passed on its first complete attempt: two identical rounds in one window/session (6/6 steps), authenticated zero-input cancellation and normal window/host cleanup; no Main repair, automatic retry, forced close or profile/cache reset. Evidence: `execution-012-ddg-argparse-01`; frozen 609-file manifest23 SHA256 `ca85163c5bb6bc8a5cde9c04ab74599be5ba3d6dc4a62a555d1d546da4b8a672`. Installed and independent acceptance are still required.

外沿标记的最终生产请求与17个已测wire逐项一致；Main九文件251项离线通过。全新argparse源码首次两轮、取消、正常收尾通过。先前candidate04、SQLite、Rust失败均保留；安装候选05仍需完整验收，未发布。

## 2026-10-13 Independent shortcut false refusal / 独立快捷提示误拒修正

字段Choice只比较规定文字，忽略独立快捷提示，将紧贴文字的灰色未接受补全交Main；完整ROI配外沿刻度，字段像素不被遮挡。19次固定诊断与预设分类符合18次：16个普通正反例全部正确，3个补全样本全部交Main，其中1个选择不满足而非证据不足。HTTP约123–197毫秒、374–594输入token仅为单请求数据，不是任务速度或通用准确率。生产请求与19次实测一致，相关89项离线通过。candidate05 Main安装验收两轮/取消/收尾通过，但独立验收把正确网址旁的独立Tab提示误认补全；候选05不能发布，修订请求待不同新流程和重建安装/独立验收。

The field-only Choice compares the exact requested value, ignores independent shortcut hints, and hands an attached gray unaccepted completion to Main. A single complete ROI with margin ticks preserves text pixels. The 19-request diagnostic matched 18 exact predeclared labels: all 16 ordinary positive/counterexamples were correct; all three completion cases requested Main, although one selected unmet instead of uncertain. HTTP 123–197 ms and 374–594 input tokens are request-only measurements, not task speed or general accuracy. Production wire matches all 19 tested requests; 89 related offline checks passed. Candidate05 Main installed acceptance passed two rounds/cancellation/cleanup, but independent acceptance falsely refused a correct URL beside a separate Tab shortcut. Candidate05 is not releasable; the revised request requires a different fresh source flow and rebuilt installed/independent acceptance.

- Failure / 失败：独立验收首轮正确输入 `https://duckduckgo.com`，未发Enter；原失败与正常关窗/宿主收尾保留。 / The first independent round stopped after correctly typed URL and before Enter.
- Root contract / 根合同：可见字段值与独立浏览器快捷提示不得混同。 / Field-value evaluation must distinguish typed text from a separate browser shortcut.
- Common fix / 通用修复：`text_value_choice_question(field_crop=True)`仅收窄灰色续接文字，单图与认证保持；没有站点词表。 / The common compact field question narrows completion to an attached continuation, without site rules.
- Regression / 回归：新增误拒原图及单字符错误期望，保留中文、路径、网址、灰色补全反例；19个wire逐项比对，API调用0。 / Retained authentic images and wrong-value counterexamples; exact offline comparison against 19 dispatched payloads.
- Safety / 输入约束：未满足与证据不足均交Main，不提交Enter，不改概率阈值、等待、重试、UIA或焦点规则。 / Both non-met outcomes retain review without Enter or automatic replay.
- Evidence / 证据：`execution-012-ddg-argparse-installed-main-01`、`execution-012-ddg-argparse-installed-sol-01`；私有实验 `field-adjacent-completion-probe`。刻度色从旧实验174改为本次实测194，旧实验结果不混记。 / The new marker color matches the tested payload; historical results remain separate.

## 2026-10-13 Fresh Git documentation run / 新Git文档流程

`execution-012-ddg-gitdiff-source-main-01`, manifest25: round1 completed all three steps automatically; round2 opened DuckDuckGo, then stopped before grounding or input for its search step. Original error was `capture_visibility_changed`, not a Decision rejection. The bound window stayed stable; one reported bottom occlusion shrank from `(974,1016,275,16)` to `(974,1024,275,8)` in a 1249×1032 capture, with another region unchanged. The failed frame and occluder identity were not saved, so no specific app or pixel cause is established. Entire acceptance failed; cancellation probe was not reached. Failure cancellation and normal owned-window/host cleanup succeeded; profile/cache retained, no retries.

源码首轮3/3自动完成；第二轮在搜索输入前因截图可见性几何变化停止，未定位、未输入。此停止不是Decision误拒，不计整套通过。日志只证明底部遮挡矩形缩小8px，不能据此确定遮挡软件。正常失败取消与收尾成功，缓存保留。14次已完成Decision、15,876输入token；3次字段值审核HTTP约152–177ms、374–504输入token，全部接受正确值；不能将不完整流程计为整体性能收益。

Pending narrow repair / 待修：only tolerate receding occlusion already covered by the original mask; reject masked candidate points before dispatch, retain all identity/current-point gates, and add no capture retry, delay or API call. New/moved/unknown occlusion remains rejected. / 仅允许旧遮罩已覆盖的遮挡退缩；原遮罩内候选点必须输入前拒绝，新增或移至旧范围外的遮挡仍拒绝，不增加等待或API。修复后使用不同curl文档流程。

## Receding-occlusion contract / 遮挡退缩合同

Only a post-capture occlusion completely contained in the original mask union can reuse the single captured frame. Keep the original mask; reject new/moved/unknown occlusion and any window binding change. Before Decision or input, the common action route rejects a point inside that source mask, with an authenticated not-dispatched receipt. Unmasked ROI routes remain unchanged; unknown masked-ROI mapping is rejected. No additional capture, wait, API request or normal-path PNG decode is added. / 仅后遮挡完全包含于原遮罩并集时保留单次截图，继续使用原遮罩；新增/外移/未知遮挡与窗口绑定变化仍拒绝。通用动作入口在Decision或输入前拒绝原遮罩内点，并认证未派发回执；无码ROI保持既有路线，带遮罩的未知ROI映射拒绝。不新增截图、等待、API或普通路径PNG解码。

Verification / 验证：worker红阶段5失败3通过；Main最终8文件153通过（含损坏路径、坐标/摘要/遮罩篡改、罩内零输入、罩外继续、无图像IO快速路径）；原19份Decision请求离线逐项一致。源码新流程尚待实际验收。 / These checks validate the common capture/input contract; fresh live acceptance remains pending.


## 2026-10-13 Target usage follow-up / 目标用法后续

Fresh curl stopped before its correctly located official result; the failed first attempt is retained. Twenty bounded image probes led to a caller-facing target contract, with no automatic target rewrite or extra request. Details and known translation-popup limitations are in [the diagnosis](DECISION_TARGET_USAGE_20261013.md). Main140 offline checks passed; new source/installed/independent acceptance remains pending. / curl首败保留，20次有界图像对照后仅更新通用目标调用契约；无自动改写或额外请求。140项离线通过，真实新流程和安装/独立验收待完成。
