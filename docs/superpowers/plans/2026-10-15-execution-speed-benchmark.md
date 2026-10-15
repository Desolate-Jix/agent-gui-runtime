## 2026-10-15 执行0.1.3发布准备已完成 / Execution0.1.3 release preparation complete

- 流程优化、真实截图提示词benchmark及执行候选02已完成。本地安装器、ZIP、SHA清单和中英发布说明位于`D:/AgentGUI-Projects/releases/instant-v0.1.3-candidate-02`，未提交、推送或发布；正式下载仍0.1.2，学习版不变。 / Pipeline optimization, real-image prompt benchmark and candidate02 preparation are complete; artifacts and bilingual notes are local, without commit/push/publication.
- 源码核心172项、另组交付/路由186项通过；候选隔离真实入口/依赖和包内43项通过。Main安装两轮Bing→Rust文档30.809/27.354秒、共41,097tokens；取消及Main核图review→continue→Google→收尾通过。 / Source and package checks passed; Main installed continuity and Main-assisted recovery passed.
- Sol用同冻结候选同一client完成取消、菜单Main角色兜底、两轮Python itertools搜索及收尾，7步完成、51,072tokens；非全自动。Main核对两张最终原图、45项独立history引用及实际用量，全部保留首败。 / Sol independently passed all7 steps and cleanup, including Main-role assistance; Main reviewed the actual evidence and usage.
- Benchmark保留集主层三分类148/160→152/160，二分类均95%，输入少1.64%；两级149/160，当前误放7/误拒1。不把有限标注一致率写成通用准确率、安全或Main介入次数提升。 / Report exact agreement separately from routing accuracy and cascade errors; no unsupported general gain claim.
- 本轮测试安装已卸载且最终零残留；首次生成pyc残留检查失败保留，382个缓存逐项与冻结源码编译结果匹配后仅在本轮安装根清理，再用原卸载器收尾。日常安装、浏览器profile/缓存保留。API累计1,748,671/5,000,000，unknown0/reserved0。 / Test installation cleanup completed; initial retained-cache failure remains recorded. Daily data is preserved and all API use is settled.
- 下一步由用户审核候选与说明后决定发布；发布时才整理执行范围提交、tag和GitHub上传。模型误拒由Main兜底，不再要求每次自动判断正确或为同菜单刷通过。 / Next is user review and a separate publication decision, not more prompt tuning or retrying for an automatic pass.

以下为历史检查点，其“当前/待验收”等字样仅描述当时。 / Earlier checkpoints below describe their original state.

## 2026-10-15 Main 接管后续行已验证 / Main-assisted continuation verified

新数据`execution-release-013-runtime-binding-handoff-01`：原请求中取消零输入通过；Bing菜单打开后两层均误拒，Main查看原after并核对6个证据SHA，通过运行时提供的caller_controls提交绑定原packet/after/evidence-set的review success；再次显式continue后，原会话地址栏输入Google并自动确认成功。菜单仅1个原job、1次点击；最终本轮窗口和宿主正常关闭。 / A fresh batch passed zero-input request-phase cancellation, then exercised real Main review of a menu rejected by both judges. Main inspected the original image, verified six evidence hashes and submitted the runtime-projected bound review, followed by explicit continuation. The same run navigated to Google and completed with one original menu click and normal cleanup.

这是Main辅助恢复通过，不是两层模型自动恢复通过；前一批取消收尾及误拒首记录保留。未调整提示词、阈值或生产源码；验收驱动仅开放既有正式同run status/review/continue控制。Main两轮正常流程、取消和接管续行现已覆盖；下一步集中构建candidate02，再验证隔离包、安装态连续与同冻结候选独立验收。 / This proves Main-assisted recovery, not automatic model recovery. Initial failures remain. Production code, prompts and thresholds are unchanged; only the external observer exposed existing same-run control APIs. Source acceptance now covers two normal rounds, cancellation and Main continuation. Rebuilt/installed and independent acceptance remain pending.

以下检查点描述各自当时状态，不覆盖本条。 / Earlier checkpoints describe their original state.

## 2026-10-15 源码连续实测与主 Agent 兜底 / Source continuity and Main backstop

当前源码739项冻结清单SHA为`e18e7a9d61d67fd4363f8328e5bf641676e8fbb51401dfe380a85dd81199229c`；不可变candidate01仍是旧源码，未重打包。 / The739-entry current-source manifest is identified above; immutable candidate01 still contains older code and has not been rebuilt.

- 正常连续：同一独立Edge资料、同一会话，两轮Bing→Rust collections文档33.2182502秒／30.5493873秒，41,173tokens；6步完成，无Main接管，关窗/finish通过。20primary、6grounding、0ordinary，省10次外层重复采图。不同任务不能作旧版受控提速比较。 / Two same-session rounds passed with normal cleanup and no Main handoff; these task timings are not a controlled speedup comparison.
- 异常批：原请求中取消、零输入结算通过；随后菜单点击成功，原after图明确可见Bing菜单，两层却均condition_not_met，按设计转Main。Main核图后cancel原等待、close_owned、finish全部通过。自动恢复未完成，主Agent接管续行尚未实测，不能把收尾成功写成恢复通过。 / Cancellation passed; a visibly open menu was rejected by both judges and handed to Main. Main verified the original image, cancelled the pending run and cleaned up. Automatic recovery did not finish; live continuation after Main review remains unverified.
- 用户最新确认：模型误拒由主Agent兜底，不以模型每次正确作为发布前提；不为这个菜单反复调提示词、调阈值或刷通过。验收检查完整证据交接、原动作不重复、Main确认后继续及最终收尾。 / The user accepts Main as the backstop for model errors. Do not require perfect judgments or repeatedly tune/retry this menu. Acceptance targets complete handoff evidence, no duplicate action, continuation after Main review and normal cleanup.
- 相关离线核心172项及另一组交付/路由186项通过；新协议历史图诊断、冻结benchmark结论保留。Decision问句选择和阈值未改。 / The172 core and separate186 delivery/routing checks passed; historical probes and frozen benchmark results remain intact. Selected Decision instructions and thresholds are unchanged.
- API累计**1,621,451/5,000,000tokens**，包括本异常批10,008tokens及取消迟返；unknown=0、reserved=0。浏览器资料和缓存完整保留，仅关闭本轮窗口。 / API usage totals1,621,451 of5,000,000 tokens, including10,008 from this adverse batch and the cancelled late response; no unknown usage or outstanding reserve. The retained test profile/cache were not cleared.
- 下一步：仅补Main审核后的实际续行/收尾验证；通过后集中构建candidate02，检查隔离依赖/输入入口并完成安装态及同冻结候选独立验收。当前未发布、未提交/推送；正式0.1.2与学习版不变。 / Next verify actual continuation/cleanup after Main review, then build candidate02 once and validate isolated entrypoints, installed behavior and independent use on the same frozen candidate. No commit, push or publication; official0.1.2 and learning are unchanged.

以下是此前检查点，时间、预算及“尚未实测”等表述仅适用于当时。 / Earlier checkpoints below describe their original time, budget and acceptance state.

## 2026-10-15 重启后定位诊断与协议最新检查点 / Post-restart grounding diagnostics and protocol checkpoint

**当前结论：机器关机后已重启，继续未完成目标；维护源码已超出不可变 candidate01，尚不能发布。以下是当前状态，后面的原文仅作历史保留。 / Current status: work resumed after shutdown and restart. Maintained source now differs from immutable candidate01 and is not ready for release. This checkpoint supersedes the historical text retained below.**

- 另组交付/识别路由/MCP六文件检查 **186 passed / 101.25s**，实际终态输出已保存；当前新Bing→Rust文档搜索两轮计划已prepare，739源码SHA冻结，未启动宿主/浏览器/API。 / A separate six-file delivery/routing/MCP group passed186 checks in101.25s. The fresh Bing/Rust two-round plan is prepared with739 source hashes; no host, browser or API was started.

- 默认失败诊断的两跳已补齐：provider 保留 stage、原模型文本、解析对象、具体错误、本地 request/capture 绑定与合法 usage，Jobs 在同一原调用记录中持久化。UTF-8 脱敏、JSON 转义 key 泄露、孤立 surrogate 及深嵌套 JSON 的三项独立复核问题均已 RED→GREEN；诊断不能覆盖原错误或丢失已知用量。 / Both missing failure-diagnostic hops are repaired: the provider retains stage, model text, parsed data, detailed error, local request/capture binding and valid usage; Jobs persists these in the original call record. The three independently found escaped-key, isolated-surrogate and deeply nested JSON issues passed RED→GREEN checks with UTF-8-safe redaction, preserved original errors and known usage.
- 历史图 repro01 本次返回的目标描述及定位坐标正确，但 request_id 为 `ag-d0906cad08714ebe92eb8d1ec568012d`，本次期望为 `ag-d0906cad08714ebe92ab8d1ec568012d`，即 `92ab→92eb` 的 a→e 回显差异，因此旧协议严格拒绝。本次诊断可解释本次失败；旧 adverse02 原响应未留存，原始精确根因仍 unknown，不能倒推。 / In this repro01 only, the target description and coordinates were correct, but the returned request ID differed from the expected ID by a→e, so the legacy contract correctly rejected it. This diagnoses this reproduction only; the original adverse02 response was not retained and its exact cause remains unknown.
- 新增显式 `response_binding='runtime'`，两份 Luna 维护示例已启用。模型输出 schema/context 不传实际 request_id/capture_id，也不要求回显；回复出现任一保留字段（含 null 或正确值）即拒绝，不能丢弃、覆盖或回退。当前同步 HTTP 调用使用开始时冻结的 capture snapshot 本地绑定，再经完整 GroundingResult、geometry、freshness、Decision 和输入门禁。 / Both maintained Luna examples explicitly enable runtime response binding. Actual runtime IDs are omitted from the model schema/context and need not be echoed. Any returned reserved field is rejected, including null or matching values; no stripping, overwrite or fallback is allowed. The synchronous call binds its frozen capture snapshot locally and retains full GroundingResult, geometry, freshness, Decision and input validation.
- 默认/显式 `model_echo` 保留旧 wire 及 profile dump 字节兼容，错 ID 继续拒绝；不自动重试，也不改变成功响应、输入权限或 Decision→普通复核→Main 的路由。 / Default and explicit model_echo preserve legacy wire/profile-dump bytes and still reject wrong IDs. There is no automatic retry or change to successful responses, input authority, or the Decision→ordinary review→Main route.
- 本轮六文件窄组 **172 passed / 7.54s**。适配新示例协议前的四个缩放 fixture 失败记录保留；它们不能被改记为首次通过。其他交付/路由相关检查已完成，另组186 passed，原输出保留；不与这172项合并冒充唯一覆盖数量。 / The six-file focused group passed 172 checks in 7.54s. Four earlier scaling-fixture failures preceding adaptation to the new example protocol remain recorded. Main's other delivery/routing group passed186 checks separately; results are retained without adding overlaps.
- 新协议历史图 repro02 有效，命中 Bing 菜单点 `(1195,114)`，原 ID/SHA 绑定正确；HTTP **4910.591ms**，**2705 input + 413 output = 3118 tokens**。repro01 为 **2792 + 329 = 3121 tokens**。两次都仅为历史图定位诊断，无桌面动作，不计实机验收；本目标累计 **1,570,270/5,000,000 tokens**，unknown=0、reserved=0。 / Runtime-bound repro02 located the Bing menu at (1195,114) with correct original ID/SHA binding, taking 4910.591ms HTTP and 3118 tokens. Repro01 used 3121 tokens. Both are historical-image diagnostics without desktop input, not live acceptance. Objective usage is 1,570,270 of 5,000,000 tokens, with no unknown usage or reservation.
- 冻结 Decision benchmark、问句选择和阈值未改；不可变 `D:/AgentGUI-Projects/releases/instant-v0.1.3-candidate-01` 的 payload/installer 未改，测试安装已正常卸载；正式 0.1.2 与学习版不变，浏览器测试资料保留。 / The frozen Decision benchmark, instruction selection and thresholds are unchanged. Candidate01's payload/installer are unchanged and its test installation was normally uninstalled. Official 0.1.2 and learning remain unchanged; browser test data is retained.
- 最新维护源码尚未完成实机正常连续流程或取消恢复，未形成新包，独立桌面验收未运行，不声称可发布。下一步仅在 Main 授权批次内，以新数据源完成实机正常连续流程及取消恢复；成功后集中构建一次 candidate02，再用同一冻结候选完成独立连续验收和正常收尾。 / Latest source has not passed live normal continuous or cancellation/recovery acceptance, has no new package, and has not had independent desktop acceptance. It is not release-ready. Next, within Main's authorized batch, validate new-data live normal and cancellation/recovery flows; after success, build candidate02 once and independently verify that same frozen candidate through continuous use and cleanup.

## 当前待办（重启后） / Current work after restart

- [x] 修复失败诊断两跳及三项独立复核问题，完成 runtime 绑定协议窄回归。 / Repair diagnostic persistence and the three review findings; pass focused runtime-binding contracts.
- [x] 完成两次历史图诊断并核对已知用量；不将其算作桌面验收。 / Complete both historical-image diagnostics and known usage accounting without counting them as desktop acceptance.
- [ ] 等 Main 记录当前交付/路由相关检查真实结果。 / Record Main's actual delivery/routing check results when available.
- [ ] 在授权批次的新数据源中完成最新源码正常连续流程与取消恢复，保留首次失败和正常收尾。 / Validate latest source normal continuous and cancellation/recovery flows with new data in the authorized batch, retaining first failures and cleanup.
- [ ] Main 通过后只构建一次 candidate02，并由独立 operator 验收同一冻结候选的连续使用和收尾。 / After Main passes, build candidate02 once and independently validate continuous use and cleanup on that same frozen candidate.

## 此前检查点（历史原文） / Earlier checkpoints (retained verbatim)

以下原正文完整保留；其中“最新/当前”、源码冻结、测试、预算或发布状态只适用于当时，不覆盖上方重启后检查点。 / Original text is preserved verbatim below. Its current/latest wording, freezes, tests, budgets and release states apply to their original checkpoints and do not override the post-restart checkpoint above.

## 2026-10-15 执行 0.1.3 候选最新检查点 / Latest execution 0.1.3 candidate checkpoint

**当前结论：候选已形成，正式验收未完成，不能正式发布。正式下载仍为 0.1.2；学习版不变。未提交、推送或发布本候选。 / Current status: the candidate exists, but final acceptance is incomplete and release is blocked. The official download remains 0.1.2; learning is unchanged. This candidate has not been committed, pushed or published.**

- 冻结执行源码为 0.1.3，共 739 项；source manifest SHA-256：`f43e352cffe60076ad217194324575bed23e73d022ed46c042fd5f0ec6e7acf2`。候选目录：`D:/AgentGUI-Projects/releases/instant-v0.1.3-candidate-01`。 / Frozen execution source: 0.1.3, 739 entries, identified by the source-manifest SHA-256 above; the external candidate is at the stated directory.
- Benchmark：39 张真实原图、30 个场景族、254 项 AI 标注案例；80 项 test 各重复 2 次，主层三分类精确一致率 92.5%（148/160）→95.0%（152/160），二分类均为 95%，输入 token 减少 1.64%。两级 cascade 为 149/160，误放 7、误拒 1，不能称为整体准确率或安全提升；AI 标注不是独立人工真值。仅落地 page-result 和 compact text-value 问句，input-field/graphic 保持 baseline。 / The frozen AI-labelled benchmark has 39 source images, 30 families and 254 cases. On 80 test cases repeated twice, primary exact agreement changed from 92.5% to 95.0%; binary accuracy stayed at 95%, with 1.64% fewer input tokens. The cascade scored 149/160 with 7 false accepts and 1 false reject, so it does not establish an overall accuracy or safety improvement. Only page-result and compact text-value instructions were adopted.
- 源码主组首结果为 963 passed / 5 failed，5 项旧问句断言失败保留；仅修测试后，受影响组 148 passed。 / The preserved broad source run returned 963 passes and 5 old-assertion failures; tests-only compatibility corrections were followed by 148 affected checks passing.
- 源码 source02：DuckDuckGo 搜索 `Python decimal documentation` 并打开首个普通结果，同会话两轮 31.476 / 32.214 秒，合计 41,806 token；同冻结候选的安装目录 Main 两轮 35.388 / 30.563 秒，合计 41,948 token。两组均为 20 次 primary Decision、6 次 grounding、0 次 ordinary，正常两轮及关闭/finish 收尾通过；不同任务或 viewport 不作旧版提速百分比，也不据此宣称普遍稳定。 / The source02 and installed Main runs each completed two rounds of the same DuckDuckGo decimal task and normal cleanup. Plan wall times were 31.476/32.214 s and 35.388/30.563 s; total usage was 41,806 and 41,948 tokens respectively, each with 20 primary, 6 grounding and 0 ordinary calls. These scenario results do not establish general reliability or a controlled speed percentage over older tasks/viewports.
- payload 隔离依赖/入口检查及 43 项针对性离线检查通过；安装检查成功，安装器 unsigned，`integration_written=false`。这不代替真实异常恢复或独立桌面验收。 / Isolated payload dependency/entrypoint verification and 43 targeted offline checks passed. Check-install succeeded; the installer is unsigned and wrote no integration. These checks do not replace recovery or independent desktop acceptance.
- adverse01：取消通过，Edge 菜单恢复被两层拒绝而失败。adverse02：取消通过，Bing 菜单恢复在 Decision 之前以 `api_grounding_invalid` 失败；定位返回未保存原文及具体校验错误，精确根因无法从现有证据还原。两组均在原取消后正常关窗并 finish；恢复失败不改记为通过。Google source01 的第二轮正确值双层误拒等既有首败继续保留。 / In adverse01, cancellation passed but Edge menu recovery failed after both judges rejected it. In adverse02, cancellation passed but Bing menu recovery failed before Decision with `api_grounding_invalid`; raw model text and the specific validation error were not persisted, so the precise cause is unavailable. Both original sessions closed and finished normally after cancellation. Recovery remains failed; earlier failures, including source01's dual rejection of a correct value, remain retained.
- 当前恢复未闭合，独立桌面验收尚未执行。Main已独立核对最后2次定位用量6,267tokens；本目标累计 **1,564,031/5,000,000 tokens**，预留0、未知0。测试安装最终正常卸载且零残留，候选、证据和原浏览器profile/缓存保留；首次卸载保留空目录的零残留检查失败及后续仅清空目录、原卸载器收尾记录均保留。 / Recovery and independent desktop acceptance remain open. Main verified the last two grounding calls and final objective usage of1,564,031tokens, with no reservation or unknown usage. Final test uninstallation left no residue; candidate, evidence and browser data remain. The initial retained-empty-directory check and subsequent normal cleanup records are preserved.

下一步：先诊断 grounding 无效响应，修复并验证异常恢复；Main 验证最终冻结候选后，再让独立 operator 用同一冻结候选完成同会话两轮和收尾。保留首败、原始用量与浏览器资料，不重试刷通过、不调阈值。 / Next: diagnose the invalid grounding response, repair and verify exception recovery, then have an independent operator complete two rounds and cleanup on the same final frozen candidate after Main passes it. Retain first failures, original usage and browser data; do not retry for a pass or relax thresholds.

## 当前计划完成状态 / Current plan status

- [x] 完成冻结 benchmark、训练/验证选择及保留集评测，仅采用 page/text 问句，并完成受影响 148 项检查。 / Complete frozen evaluation, adopt only page/text instructions, and pass 148 affected checks.
- [x] 形成 0.1.3 执行候选及外部双语简介；payload 隔离检查、43 项针对性检查和 check-install 通过。 / Prepare the execution candidate and external bilingual draft notes; pass isolated payload checks, 43 targeted checks and check-install.
- [x] Main 源码及同冻结安装候选各完成正常同会话两轮和正常收尾。 / Complete Main's normal two-round source and installed flows with cleanup.
- [ ] 定位并闭合 Decision 之前的 `api_grounding_invalid`，不预定根因。 / Diagnose and close the pre-Decision invalid grounding response without presupposing its cause.
- [ ] 修复并验证最终候选的异常/菜单恢复；当前两组恢复均未通过。 / Repair and verify final-candidate exception/menu recovery; both current attempts remain failed.
- [ ] Main 通过后，以同一冻结候选执行独立桌面两轮及收尾；当前仅准备，未执行。 / After Main passes, independently execute two rounds and cleanup on the same frozen candidate; currently prepared only.
- [x] Main核对最终预算1,564,031tokens、预留/未知0，完成测试卸载、最终简介及可核对的candidate/readiness记录；正式验收仍未闭合。 / Main completed budget, uninstall, final notes and reviewable candidate/readiness records; release acceptance remains incomplete.

## 历史记录 / Historical records

以下保留原文均为历史检查点；其中“当前/最新”、预算、构建或验收状态仅适用于当时，不覆盖上方最新检查点。 / The retained original text below is historical. Its “current/latest” wording, budgets, build and acceptance states apply only to their original checkpoints and do not override the update above.

# Execution speed and Decision benchmark implementation plan

> **For agentic workers:** Use the existing maintained execution path and the code implementation loop. Work in bounded slices with tests; Main integrates and verifies. / 复用维护执行链，小步验证，Main负责整合。

**Goal:** Reduce actual execution latency, evaluate Decision prompts on independently labelled real screenshots within a5,000,000-token API ceiling, and prepare the next execution release. Learning mode is outside this release. / 提速、真实截图评测、准备执行版；不发布学习版。

**Architecture:** Keep one input owner, one MCP connection and the existing gated executor. Optimize observation work without bypassing fresh evidence or the Decision→ordinary Luna→Main cascade. Benchmark evidence and truth remain separate from provider input. / 不另建执行器，不降低审核；真值不发给模型。

**Tech Stack:** Python, pytest, Pillow, httpx, existing maintained capture/action APIs.

**Spec:** User goal in this conversation; measured baseline in `docs/verification/GOOGLE_JAVA_FIXED_20261015.md`.

**Current priority / 当前顺序:** 先优化流程、再benchmark。04正常连续两轮与06取消／同会话恢复已完成，因此随后启动冻结评测；最终发布候选仍需集中验收。 / Pipeline-first order was followed: normal continuous04 and cancellation/recovery06 checks preceded paid frozen evaluation; the final consolidated release candidate still needs acceptance.

## Global constraints / 全局约束

- Real API ceiling:5,000,000 tokens across this objective, including retries/secondary requests. Reserve usage before sending; preserve reservations for unknown outcomes. No automatic retry. / 总预算含二层与未知结果，不自动重试。
- Retain `D:/AgentGUI-Projects/test-profiles/amadeus-codex-runtime-edge`; no browser data cleanup. / 保留原测试profile。
- Only project-maintained desktop observation and gated action APIs. / 禁止原生Codex Computer Use。
- Preserve thresholds, original target, screenshot-coordinate mapping, freshness and action permissions. / 不靠松门禁提速。
- No push/publication until the requested preparation and reviewable evidence exist; this goal authorizes preparing the release, not silently publishing. / 本轮准备发布，不自动公开上传。
- Preserve all unrelated uncommitted work. UTF-8 and Chinese comments. / 保留其他改动。

## Review focus / 核对重点

1. Failed launch never dispatches a queued plan into an old window. / 启动失败不执行后续输入。
2. Removed diagnostic work cannot become missing action evidence. / 去重复不能漏证据。
3. Duplicate scenes and opposite labels cannot leak across dataset splits. / 同场景不跨集。
4. Timeout/unknown usage cannot reset the token budget or count as a correct negative. / 未知不算答对，也不退预算。
5. A prompt winner is frozen before held-out evaluation; no retuning on that result. / 保留集先冻结再评测。

## Task1: Optional grounding reasoning experiment / 定位推理实验入口

**Files:** `app/vision/external_grounding_api.py`, `tests/test_external_grounding_api.py`, a separate experimental Luna profile.

- [x] Add failing tests for omitted/null wire compatibility, explicit none and unsupported protocol rejection.
- [x] Implement optional `reasoning_effort`; preserve all other request fields and coordinate mapping.
- [x] Run scoped grounding/config tests. Keep the normal example unchanged until the real comparison passes.
- [ ] Optional follow-up, not a release gate: compare default versus none on independently labelled targets. Normal grounding defaults remain unchanged; no unmeasured gain is claimed. / 可选后续，不阻塞本轮；默认定位推理未改，不宣称收益。

## Task2: Remove measured pipeline overhead / 流水线提速

**Files:** Start with `app/execution/local_direct_step.py`, `app/core/verifier.py` and their maintained tests; edit only after locating the shared contract.

- [x] Identify the smallest change that shares same-phase observation or unifies diagnostic/settled observation without stale evidence.
- [x] Write regressions for fresh post-action evidence, failed/unknown dispatch, cancellation and default compatibility.
- [x] Implement and run relevant unit/contract coverage. Main241passed; two old fixture failures corrected without changing assertions. See `docs/development/SETTLED_OBSERVATION.md`.
- [x] Prepare the complete caller plan before launch; submit promptly after verified window binding with the same connection. Server gaps201ms/160.999ms; the next driver measures6.132ms before its client call (different boundaries). / 已验证预装计划与同会话接续，区分计时边界。
- [x] Verify a fresh real flow twice continuously with normal cleanup, using the retained profile. Newpython-json flow37.647s/26.325s, noMain handoff;739 source hashes verified. Keep the original53.544s baseline and failures intact. / 新流程两轮完成，旧首败保留，不作不同任务受控提速比较。
- [ ] Verify interruption/cancellation, dialogs and recovery on the final frozen release candidate; this04 candidate has offline coverage only for those cases. / 最终发布候选仍须实机异常与恢复覆盖。
- [x] Repair wide-field visual detail without changing the source point/bbox or question. Main245related checks pass; fresh pathlib round1completed44.908s, round2model rejection preserved. / 输入框局部放大与245项回归通过；连续验收尚未通过。
- [x] Eliminate candidate full-frame annotation encoding only when the provider replaces it with the composite; preserve complete outgoing HTTP bodies and all authentication rereads. Main333related tests pass; fixed-image CPU preparation+provider323.1→163.7ms is separate from API/task latency. / 已移除未上传的重复标注编码，完整wire不变；CPU测量不冒充任务收益。

**Task2 checkpoint / 流程阶段检查点:** 新pathlib首轮自动完成，第二轮与后续新sqlite首轮均被两层模型nonpass阻断，原run均正常取消与清理。用户再次明确流程优先，因此继续处理截图、步骤衔接及会话连接的固定开销；不因模型误拒而提前启动Task3付费比较，也不反复完整实测碰运气。保留所有首败，源码验证后再集中验收，不把连续项伪记完成。 / The user's latest steering keeps pipeline overhead first. Model rejection does not advance paid prompt evaluation ahead of that work; preserve failures and consolidate live acceptance after source verification.

### Task2 follow-up / 本轮流程补充

- [x] Profile native BGRA decoding on three retained source images; remove the intermediate RGB conversion with byte-identical PNG output. / 三图核对原生像素解码，输出字节保持一致。
- [x] Consolidate the outer before-input report image with the same invocation's fresh inner capture; keep a durable per-step copy and all dispatch checks. / 默认委派视觉/Enter内部目标命中；真实两轮省10次外层采图，持久PNG一致。无目标本地路线保持原行为。
- [x] Retain Decision connections across normal inter-step grounding gaps; verify reuse, expiration and close on local loopback. / 60秒连接复用、过期与关闭的回环验证通过；Main连接/时限相关131项通过。
- [x] Audit transition scheduling before changing it. Terminal review already prepares/enqueues the next step in the same advance; no extra200ms delay exists there. / 已知终态同次推进，无需修复不存在的额外等待。
- [ ] Consider one-shot trusted job-completion notification separately; at most200ms discovery delay per job, net benefit unmeasured. Do not expand the architecture in this slice. / 完成通知属于后续小优化，当前不扩展调度架构。
- [x] Run affected contracts and review the integrated source before live work. Main579 related checks passed, then one new two-round live flow completed; current-state documentation follows that evidence. / Main579项通过后完成新流程两轮，文档按实际结果同步。


### Request-phase cancellation checkpoint06 / 请求阶段取消检查点06

- [x] Preserve internal cancellation across compound input and form filling without rewriting prior False/True/None dispatch facts. New8 checks and Main451 affected checks pass. / 内部typed取消透传，实际副作用由原账本保存。
- [x] Run real request-phase cancellation, then a new menu/navigation task in the same client and window on frozen06; two recovery steps and normal cleanup succeeded. Keep05 failed separately. / 06取消、同会话菜单和导航完成，05首败保留。
- [x] Audit external Luna client lifetime: it already uses60-second keepalive in04, with measured inter-request idle gaps4.575–9.313seconds; no duplicate client optimization or unmeasured TLS claim. / 已有长期连接，不重复修改已完成项。
- [ ] Revalidate the complete final frozen release candidate after prompt selection. Current06 recovery evidence does not replace full three-step/two-round installer acceptance. / 最终发布候选仍集中复验；冻结benchmark现已完成第一层评测，二层诊断另记。

## Task3: Reproducible real screenshot benchmark / 真实截图评测

**Evaluation checkpoint / 评测检查点:** 04正常连续流程及06取消恢复之后运行训练312、验证280、保留320次请求，均已结算。39张原图、30个界面族、254个AI初标/Main AI复核案例，104/70/80分集；界面族不跨集，但不是完全独立host会话分集。保留集三分类92.5%→95%，二分类通过判定均95%，误放／误拒不变。二层Luna诊断单独执行；不得用HTTP延迟冒充实际动作提速。 / Frozen evaluation follows pipeline acceptance. AI-reviewed labels and correlated cases do not establish general accuracy. See `docs/verification/DECISION_PROMPT_BENCHMARK_20261015.md`.

**Files:** Reuse existing experiments as inputs, add a maintained Decision benchmark script and focused tests, plus an external frozen dataset/evidence directory.

- [x] Inventory real screenshots/receipts and source-SHA/capture provenance; AI labels reviewed by Main AI, not humans. / 来源与标签性质已明确。
- [x] Cover field containment, graphics, entered text, page outcomes and difficult negatives; real screenshots only. Insufficient-evidence cases remain sparse. / 覆盖四类，证据不足类偏少。
- [x] Freeze scene/UI-family splits before API; no source/crop/family leakage. Two capture-host sessions span splits, so do not claim independent-session evaluation. / 无原图或界面族泄漏，不夸大会话独立性。
- [x] Implement a resumable append-only usage journal with pre-dispatch token reservations and a hard5,000,000 ceiling; reject conflicting IDs and count unknown usage conservatively.
- [x] Test exhaustion, resume, invalid replies, leakage and scoring; Main84 tool tests passed. / 工具离线84项通过。
- [x] Interleave baseline and small single-variable variants with fixed seeds; preserve all raw replies, latency, usage and rejection history. / 原始912次结果保留。
- [x] Freeze train selection, validate with a predeclared revert rule, then freeze final prompts before untouched held-out API evaluation. / 先冻结再保留集，不按test调参。
- [x] Evaluate164 secondary requests separately. New mix corrected3/4 false rejections but added3 false accepts; final149/160, seven false accepts and one false rejection. / 不能称两层整体准确率或安全提升。
- [x] Adopt only frozen page/text instructions; verify254 questions and226 full provider bodies, with text-value protocol qualification. Fix prompt-revision authentication and affected test assertions; Main148 affected checks passed after the preserved broad-run failures. / 未按test改阈值；旧结果不能认证为新问句。

## Task4: Release preparation / 执行版发布准备

**Files:** Relevant public README, development/verification documents, version and packaging manifests after the candidate is frozen.

**Read-only readiness audit / 只读准备核对:** 执行版号取`app/instant_mcp.py:INSTANT_VERSION`（已发布0.1.2），不取pyproject的0.3.0。只走执行组件与`--component execution`安装器，沿用依赖锁。04的739源码SHA是历史检查点，之后已增加取消、报告与提示词修改，不能声称当前源码相同。静态载荷核对572源文件／57资源；9项dirty学习UI未纳入，6项app JSON均为维护schema。旧learn/Hybrid分支9个缺失schema不是默认execution链已证实阻断，也不能称该旧分支已验证。最终载荷和隔离预检仍另做。 / Historical source checks and static payload inventory do not replace final isolated packaging or live acceptance.

- [ ] Review the entire final diff and remaining failures; do not package unrelated learning changes as execution claims.
- [x] Close current README-linked delivery resources, including the benchmark report; collect19 entries/572 sources/58 resources and inspect the exact learning-resource intersection. Final copied payload remains separately checked. / 静态清单闭合，复制包另验。
- [ ] Run proportionate final contract/dependency checks and Main continuous real acceptance before independent acceptance of the same candidate.
- [ ] Prepare the next execution patch version, bilingual release notes, known limitations and measured before/after results; build once after source acceptance.
- [ ] Verify isolated bundle dependencies and installer behavior; retain logs/manifests and browser data.
- [ ] Present release-ready artifacts and unresolved limitations. Mark this objective complete only when all requested evidence and preparation are verified.

No speed/accuracy target is represented as already achieved. The ceiling is a maximum, not a spending target. / 不预填收益；500万是上限，不是必须用完。
