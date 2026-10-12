# 输入后仅核对内容：真实 API 重放 / Text-only value API replay

2026-10-12，用户要求再次测试。使用此前网址输入误拒的同一张原始截图和真实点击回执，未操作浏览器或修改资料、缓存、旧账本。新语义问题只比较目标字段显示文字与 expected_text，不核验焦点、可行性或后续跳转。 / At the user's request, the retained URL false-refusal image and actual click receipt were replayed with text-only value checks. No desktop, browser-data/cache or historical-ledger changes occurred.

实际问题 / Exact question:

> Does the target field display exactly action.expected_text? Identify the field by action.field.field_goal and read its displayed text.

第一阶段：提示词对照（8次请求） / Stage one: prompt comparison (eight requests).

两组使用同一个 Choice 问题。双图保留原图、原细节裁剪和历史点击标注；单图只保留标注整图，图片说明相应改为读取该图文字。所有调用走维护 provider，无重试。 / Both arms use the same Choice question. Dual-view retains the original, detail crop and annotation; marked-only sends one annotated full frame with a matching image explanation. All calls use the maintained provider with no retries.

| 期望内容 / Expected text | 双图 / Dual-view | 仅标注图 / Marked-only |
|---|---|---|
| `https://www.google.com`，与截图一致 | 匹配 2/2 | 匹配 2/2 |
| `https://example.com/`，错误域名 | 正确拒绝 1/1 | 正确拒绝 1/1 |
| `https://www.google.comx`，末尾多一字符 | 正确拒绝 1/1 | 正确拒绝 1/1 |

8次请求全部与预期一致。反例仅改变诊断期望文字，没有伪造新的真实输入回执。原图文件哈希在测试前后都保持一致。 / All eight responses matched expectations. Negatives alter diagnostic expected text only, without fabricating new input receipts. Source-image hashes remain unchanged.

正确网址：双图的 Choice confidence 为1.00，单图为0.72；均按直接 Choice 路由，不用置信度重新设门槛。这是模型输出，不是准确率估计。 / Positive confidence was1.00 for dual-view and0.72 for marked-only, without threshold re-gating; these are model scores, not measured accuracy.

正确案例单次 input_tokens 为4298对2320；同样四次调用每组总计17192对9280，单图减少46.0%。HTTP中位数见本地summary.json（包含传输准备及网络，不是整条GUI流程用时）。 / Positive input tokens were4298 versus2320; totals across four requests per arm were17192 versus9280, a46.0% reduction. HTTP timing includes transport preparation/network and is not full GUI latency.

这张固定截图的误拒在新问题下消失，但仅一个画面、三个期望变体，不能声称广泛准确率或连续桌面稳定。新问题和相关上下文同时简化，不能据此断定旧拒绝的唯一原因就是焦点。该第一阶段仅标注图为诊断路线，未改生产默认；随后按用户新要求切换默认，见第二阶段。 / This fixed-image refusal disappeared, but one image with three expected-text variants is not a general reliability benchmark. Both question and context were simplified, so focus cannot be isolated as the sole old cause. At this first stage, marked-only was diagnostic. The subsequent user-requested production-default switch is recorded below.

证据 / Evidence: `.superpowers/sdd/2026-10-12-choice-runtime/text-only-value-replay/` contains `plan.json`, `dispatches.jsonl`, `results.json`, `summary.json` and each case's `prompt-and-images.md`. Script: `text_only_value_probe.py`. Previous source verification remains317 offline checks passed; this retest adds eight real API calls, not additional offline cases.

## 第二阶段：正式默认仅发送标注图 / Stage two: annotated-only production default

用户要求“以后方案都使用已标注图 再次测试”。维护provider现在对有candidate_annotation或executed_click_annotation的帧只发标注整图，不发送原图或字段裁剪；原图文件、SHA及认证绑定本地保留。没有可用标注的结果、动态内容和旧记录仍发原图，不虚构点击坐标。标记遮挡必要细节时判证据不足。 / At the user’s request, annotated candidate/executed-click frames now upload only one marked full image. Original files, hashes and authentication remain local. Unmarked result/temporal/legacy frames retain originals; points are not invented. Obscured required details mean insufficient evidence.

Main实际运行相关21个测试文件：**462 passed in18.44s**，无失败或跳过。覆盖单标图/双帧各一标图、避免多余裁剪、旧无标注路径、原图不可变、回执认证、Choice与纯视觉输入集成。 / Main ran21 relevant test files:462 passed in18.44s, with no failures/skips. Coverage includes per-frame single-image upload, no redundant marked-field crops, legacy paths, source immutability, authenticated receipts and visual Choice integration.

正式provider默认传输未做诊断改写，真实请求4次、无重试：

| 内容 / Case | Choice | HTTP ms | Input tokens |
|---|---|---:|---:|
| 正确网址，第1次 / Correct URL 1 | condition_met | 480.7 | 2320 |
| 正确网址，第2次 / Correct URL 2 | condition_met | 221.1 | 2320 |
| 错误域名 / Wrong domain | condition_not_met | 236.0 | 2319 |
| 网址末尾多一个x / Extra trailing x | condition_not_met | 219.6 | 2321 |

HTTP中位数约228.5ms；这是客户端HTTP耗时，不能全部归为模型推理。正确网址两次confidence均0.72，直接采用Choice而非阈值复判。四次请求输入token共9280；原图哈希复核未变。 / Median client HTTP time was about228.5ms, not isolated inference latency. Both positive confidence values were0.72, with direct Choice routing rather than threshold re-gating. Total input tokens:9280; source hashes remained unchanged.

本轮合计12次付费API请求：第一阶段8次对照，第二阶段4次正式默认验证，不能把它们合并成12个独立画面。没有桌面动作、浏览器启动或缓存清理；源码未发布、安装器未更新。完整Google→java→首个链接及同资料目录连续流程仍需后续验证。 / The turn used12 paid API requests across the8+4 stages, all based on one retained image rather than12 independent scenes. No desktop/browser/cache operations or release occurred; continuous Google→java→first-result execution remains open.

证据 / Evidence: `.superpowers/sdd/2026-10-12-choice-runtime/marked-default-offline.xml` and `marked-default-replay/{plan.json,dispatches.jsonl,results.json,summary.json}` plus per-case `prompt-and-images.md`. Harness:`marked_default_probe.py`; offline request capture confirms one uploaded image per case, while live mode uses the production provider without a custom transport.

## 第三阶段：同资料目录完整流程首次失败 / Stage three: first live full-flow failure

2026-10-12 实机复测未完整通过：同一保留 Edge profile 中，Google网址输入及跳转自动通过；搜索java前，空框Ctrl+A后的 after_selection Choice 返回 evidence_insufficient，尚未输入java或按Enter。Main核对空框后显式改为 clear_existing=false 的剩余计划，被现有接口以 visual_input_append_unsupported 拒绝；没有绕过或重复原输入。首次失败保留，不能用此前固定截图4/4覆盖。失败层已定位，具体语义/证据原因待查。Decision共8次调用。窗口正常关闭、宿主exit0且cleanup_verified=true，profile与缓存保留；未改生产代码、阈值或安装器。 / The retained-profile live run did not complete: Google URL input/navigation passed, then Choice returned evidence_insufficient after Ctrl+A in the empty search field, before typing java or Enter. A Main-reviewed no-clear remainder was rejected as visual_input_append_unsupported. No bypass or replay occurred; retain this failure separately from the earlier4/4 fixed-image result. The failing layer is known, but the semantic/evidence cause remains open. Eight Decision calls; normal window close, host exit0 and verified cleanup, with profile/cache retained. No production-code, threshold or installer change.

证据 / Evidence: `D:/AgentReviewAcceptance/native-focus-geometry-20261012-marked-live-01/{events.jsonl,main-review-replan.json,final-summary.json,isolated-browser-cleanup.json}`。下一步修复并离线验证空字段全选合同，再进行相关实机复测；本轮不追记为全自动成功。 / Next repair and verify the empty-field selection contract offline before another live regression; this run is not autonomous success.
