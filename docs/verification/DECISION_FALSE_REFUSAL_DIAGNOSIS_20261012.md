# Decision 误拒只读诊断 / Read-only false-refusal diagnosis

日期 / Date: 2026-10-12

本轮只读原始测试证据，离线重建请求与重放路由；没有真实 API 请求、桌面动作、阈值调整或产品实现改动。浏览器数据保护要求另已写入主库及当前工作树的 AGENTS.md。 / This investigation reads historical evidence and reconstructs requests and routing offline. It makes no real API requests, desktop actions, threshold changes or product implementation changes. Browser data preservation instructions were separately added to both checkout AGENTS.md files.

## 结论 / Findings

1. Java 页面已打开的记录确实停在审核：条件成立 `0.68`、需要主 Agent 审核 `0.83`、可见错误 `0`。当前生效通过阈值为 `0.80`，转审核阈值为 `0.70`，两项均独立阻止继续。离线使用原分数重放当前策略，逐项重现原结果；没有发现分数错位或结果解释反转。该次 HTTP 耗时约 `381 ms`，不是 API 超时。 / The loaded Java page did stop for review: condition `0.68`, review `0.83`, visible error `0`. Active thresholds were `0.80` for success and `0.70` for review. Both independently prevent continuation. Offline policy replay reproduces the recorded result; no score misbinding or inverted interpretation was found. HTTP duration was about `381 ms`, not a timeout.

2. 发送材料存在值得优先验证的上下文过宽问题。主条件只要求目标网页正文已显示，但共享上下文仍包含“完成从 Google 网址输入到打开第一个普通结果”的全过程；`step_goal` 是包含“第一个、非广告”的动作与核验 JSON。请求只有一张跳转后的截图，无法单独证明之前点击的是搜索结果第几条。`needs_agent_review` 又询问是否存在超出冻结状态的额外选择或变化。上下文混入单张图无法确认的历史事实，是误拒的合理嫌疑，**尚未通过同图 API 对照实验证明是这次低分的唯一原因**。 / The request has potentially overbroad context. Its explicit condition only requires loaded destination content, but shared context includes the entire Google navigation task and first non-sponsored-result selection. `step_goal` serializes the action and verification. A single after image cannot establish the earlier result rank. The review question additionally asks about extra choices or changes outside frozen states. Historical requirements exceeding the supplied evidence are a plausible cause, **not a proven unique explanation of the scores without a controlled same-image API comparison**.

3. 原始 Java 截图经查看为已加载的 Java/Oracle 页面。截图 SHA-256 与 ledger 一致，尺寸 `2412 × 1040`；本地证据上传路径保留原始图片字节。原冻结版本与当前 provider、native evidence adapter 文件哈希一致，离线重建得到三个 predicate 问题。重建产物是依据绑定证据和匹配源码生成，**不是当时截获的 HTTP 原件，也不证明模型内部看图方式**。 / The original image visibly shows a loaded Java/Oracle page. Its hash matches the ledger and its dimensions are `2412 × 1040`; the local upload path preserves original image bytes. Provider and native adapter hashes match the run freeze. Offline reconstruction produces three predicate questions. This is a reconstruction from bound evidence and matching source, **not an original HTTP capture or evidence of internal model image processing**.

4. 输入值 `0.41` 属于更早的一次请求。原生读取、预期文本、实际输入均是完整 `https://www.google.com`；相关回执摘要匹配，截图也完整显示网址。同期记录指出旧提示仍强调只看图，未说明已绑定原生值的用途；但没有找到该次完整 HTTP 文本原件，不能声称已证明模型低分的唯一原因。修正后的五条真实值判断为 `0.98 / 0.98 / 0.95 / 0.97 / 0.98`，均已采用通过。**旧 `0.41` 不能算当前持续故障，也不能用后续五次通过宣称长期稳定性。** / The `0.41` value assessment is historical. Native, expected and typed text all equal the complete Google URL; receipt hashes match and the screenshot shows the complete URL. Contemporary records identify an old visible-only prompt that did not explain the bound native value evidence, but its complete HTTP text body was not located. Five subsequent actual value assessments scored `0.98 / 0.98 / 0.95 / 0.97 / 0.98` and were adopted. **The old `0.41` is not evidence of an ongoing defect; five later successes are not a long-term reliability estimate.**

5. 当前值条件仍要求完整文字可见且无隐藏、裁切，同时 native 说明允许使用完整原生值判断相等。这比单纯“值输入正确”严格，长文本或网址省略时可能误拒；旧 `0.41` 原图没有裁切，不能把此张力直接认定为其原因。 / Current value conditions still require complete visible text with no clipping while native instructions allow complete native values to establish equality. This exceeds simple value correctness and may reject elided or scrolled text. The historical `0.41` screenshot was not clipped, so that tension does not establish its cause.

## 下一步建议 / Recommended next step

先固定阈值和截图，比较当前问题与“只检查本步可见结果、只对实际阻碍转审核”的精简问题；保留真正错误、遮挡和未完成的反例，不能只用成功截图提高分数。已完成步骤的历史来源应由前一步证据承担，不把未提供的历史交给单张结果图猜。输入值判断明确原生完整值与截图各自证明的事实。 / Hold images and thresholds fixed and compare the current questions against scoped current-result and concrete-obstacle questions, including genuine errors, occlusion and incomplete states. Previous-step evidence should establish action provenance rather than asking a single after image to infer it. Separate what complete native values prove from what images prove.

这不是已执行修复或新一轮模型验收。API 的 predicate 是条件为真的估计，返回结果本身不附推理解释；不能把分数直接当成识别准确率。 / This is a recommendation, not an implemented fix or a new model acceptance run. Predicate probability estimates whether a condition is true and does not itself explain the reasoning or measure recognition accuracy. [OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions)

## 浏览器数据补充 / Browser data follow-up

用户明确禁止测试删除或重置浏览器数据。主库和当前工作树 AGENTS.md 已同步，原文已备份并读回核对。后续测试要求独立资料目录并保留，结束只关闭本轮窗口；尚未新增或运行测试启动器。 / The user prohibits browser-data deletion or reset during testing. Both checkout AGENTS.md files were updated, backed up and read back. Future tests must use a retained isolated profile and close only their own windows; no new test launcher has been implemented or run.

最近三次启动记录只有 `msedge.exe`，未指定 `--user-data-dir` 或 `--profile-directory`；最后一次 Java 流程复用之前的窗口。已检查的清理脚本仅核对身份后发送单窗口 `WM_CLOSE`，近期脚本搜索未找到删除浏览器缓存、重置 profile 或修改浏览器启动入口的指令。**确认缺少测试隔离，但缓存丢失原因仍未知；未找到删除指令不能证明历史没有删除。**没有读取私人浏览历史、Cookie 数据库、凭据或 API 密钥。 / The three recent launches pass only `msedge.exe`, without a user-data or profile-directory argument; the final Java flow reuses the earlier window. Inspected cleanup scripts validate identity and send single-window `WM_CLOSE`; recent-script searches found no browser cache deletion, profile reset or launch-entry modification. **Missing test isolation is confirmed; the reported data-loss cause remains unknown. Absence of a deletion instruction in this scope does not prove no historical deletion occurred.** No private browsing history, cookie databases, credentials or API keys were read.

证据 / Evidence: `.superpowers/sdd/2026-10-12-decision-false-refusal-analysis/browser-data-findings.json`.

## 证据与验证 / Evidence and verification

- 原 Java 请求 / Original Java request: `task-decision-7d84a39cddedbdcd49b0d6f843116f13`, session `D:/AgentReviewAcceptance/final-button-flow-1791737942461/session-fd8cfb78da88421293a22fe493680b35`.
- 本轮产物 / This investigation: `.superpowers/sdd/2026-10-12-decision-false-refusal-analysis/final-page-ledger.json`, `page-request-reconstruction.json`, `field-findings.json`.
- 已运行 / Executed: `read_page_judgment.py`（ledger 只读 / read-only ledger）与 `reconstruct_page_request.py`（假 HTTP 客户端，哈希、图片绑定、路由结果断言通过 / fake HTTP client; source hashes, image binding and routing assertions passed）.
- 未运行 / Not run: 新的真实 API 请求、桌面测试、准确率 benchmark、浏览器启动或清理 / new real API calls, desktop tests, accuracy benchmark, browser launch or cleanup.
