# 两条目标核验路线的真实检查 / Live target-check verification

2026-10-14，`codex/dev-decision-api`，未发布源码；源码基线 HEAD `63c95fa0c29cce9773040518b1df626076eaa56b`，工作树包含未提交实现。 / Unreleased working-tree implementation; HEAD alone does not identify this candidate.

## 结果 / Outcome

同一维护客户端、MCP会话、独立保留的Edge资料目录及窗口，连续执行两个不同任务。**一轮在输入前失败，一轮首次自动完成；没有达到连续两轮通过。** 两轮之间未修源码、改阈值、裁剪或配置。 / One attempt stopped before input; the next distinct task completed automatically on its first attempt. Two consecutive passes were not achieved. Source, thresholds, crop and profile stayed fixed.

| 任务 / Task | 原始结果 / Original result | 调用方墙钟 / Caller wall |
|---|---|---:|
| 搜索并打开Python functools官方文档 / Search and open functools docs | 地址栏目标被Decision拒绝，普通Luna复核超时；零输入，原等待随后取消 / Pre-input rejection, secondary timeout, no input; original run cancelled | 21.348 s |
| 搜索并打开Python heapq官方文档 / Search and open heapq docs | 两步自动成功，执行期间无Main接管 / Both steps completed without Main intervention | 34.428 s |

计划的两步为地址栏填写带查询参数的Bing URL并提交，再点击第一个匹配的官方文档链接。不是Google→搜索框→结果的三步计时。启动窗口另计1.407秒，初始截图另计0.708秒；表中不含Main读图、诊断与收尾等待。 / The two-step plan enters a Bing query URL and opens the first matching official result; it is not the earlier three-step Google benchmark. Launch, initial inspection, Main analysis and cleanup are excluded from plan wall time.

Main核对第二轮原始最终PNG：地址为 `https://docs.python.org/3/library/heapq.html`，标题为 `heapq — Heap queue algorithm`。运行记录为completed、2/2成功。 / Main inspected the original final capture and confirmed the official URL and heading, consistent with the completed 2/2 receipt.

## 判断明细 / Decision details

| 检查 / Check | Decision选择 / Primary choice | 二层 / Secondary | 结果 / Result |
|---|---|---|---|
| functools地址栏候选 / Address-bar candidate | condition_not_met，概率0.94，独立confidence 0.91 | ordinary_review_timeout | 停在输入前 / No input |
| heapq地址栏候选 / Address-bar candidate | condition_not_met，概率0.59，confidence 0.38 | condition_met | 自动续行 / Continued |
| heapq输入内容 / Entered value | condition_met | 未触发 / Not needed | 继续 / Continued |
| heapq提交前地址栏 / Address bar before Enter | condition_met | 未触发 / Not needed | 点击与Enter / Click and Enter |
| heapq搜索结果 / Search result page | condition_met | 未触发 / Not needed | 继续 / Continued |
| heapq官方链接 / Official result link | condition_met | 未触发 / Not needed | 点击 / Clicked |
| heapq最终页面 / Final page | condition_met | 未触发 / Not needed | 完成 / Completed |

四次带target_check的目标核验，首层两次通过、两次拒绝；两次拒绝均发生在正确地址栏候选，Main按原图核对为误拒。一次由普通Luna纠正，一次复核超时。只有一个链接正例，没有困难反例；不能将这个小样本视为通用准确率或安全性统计。Choice直接选择控制路由，没有新增概率阈值。 / Of four target checks, two passed directly and two correct address-bar candidates were rejected. One secondary review corrected a rejection; the other timed out. This tiny positive-only sample does not establish general accuracy or false-accept protection. Routing uses Choice directly.

首败点为原图 `(1120,59)`，框为 `(75,43,2260,36)`，视口2560×1400。原定位图与审核新图的地址栏区域像素完全相同。独立只读审计未发现坐标、映射或标注错位证据；**拒绝原因仍未知**。 / The first point is inside the visible address bar; the field pixels did not change. Independent read-only auditing found no mapping or annotation defect. The model's reason remains unknown.

首败请求按冻结源码离线重建，完整绑定摘要与真实ledger一致：`0dfe3e2701385edab1dd96841299d0b6ea38f4d9cbb607ec5c5e22125766cdaf`。问题确实只核对点在原目标框内，不要求焦点、输入内容、未来结果或多类别身份。重建PNG的SHA为 `66b0430acf7133b39b24ac15e091d9578827f2cb94e82c38550b4d7b577ced0d`。**这是可验证的重建，并未抓取真实网络wire。** / Reconstructed bindings, question, image and mapped centers agree with the ledger and frozen source. This is an offline reconstruction, not a captured HTTP payload.

## 速度与用量 / Timing and usage

| 第二轮已返回响应 / Successful round's returned responses | 次数 / Count | 输入token / Input | 输出token / Output | HTTP合计 / HTTP total |
|---|---:|---:|---:|---:|
| 定位Luna / Grounding | 2 | 6,221 | 826 | 12.803 s |
| Decision首层 / Primary Decision | 6 | 10,695 | 0 | 2.580 s |
| 普通Luna复核 / Ordinary review | 1 | 820 | 6 | 1.884 s |
| 合计 / Total | 9 | **17,736** | **832** | **17.268 s** |

第二轮总token为18,568。模型HTTP总和小于34.428秒整轮墙钟；差值包含截图、输入、等待、持久化等本地处理，不归因于某一个组件。Decision目标核验和输入值采用裁剪标图；两个页面结果核验合计7,742输入token，是另一独立用量项。 / The successful round used 18,568 tokens. Remaining wall time includes capture, input, waits and persistence; it has not been attributed to a single component. Page-result checks alone used 7,742 input tokens.

首轮定位HTTP8.694秒、服务8.935秒；Decision首层HTTP1.897秒；两级服务整体8.015秒。二层共享8秒总期限并超时，未保存独立HTTP、usage或provider ID。不能把8.015−1.897秒全部算成二层HTTP，也不能把其用量写成零。 / The first round exhausted the shared eight-second review deadline. Secondary latency and usage are unknown, not zero.

本批已返回响应共11个：3次定位、7次Decision及1次成功普通复核。另有1次超时复核预留；预算used=9含两次复核预留，不能单凭预留证明超时请求的网络派发。已知总用量至少21,602输入、1,311输出，合计22,913 token；缺少的超时用量未知。不与此前不同提示词、页面和任务的25.3–34.5秒记录作加速百分比对照。 / Eleven responses returned; one additional review reservation timed out without complete dispatch/usage evidence. Known usage totals 22,913 tokens, with possible timeout usage unknown. Earlier differently configured tasks are not a controlled speed baseline.

## 证据、收尾与限制 / Evidence, cleanup and limits

证据根 / Evidence root: `D:/AgentGUI-Projects/evidence/target-check-live-20261014-01`。

- `responses/10-plan.json`保留首败等待，`11-cancel.json`确认原run取消；`20-plan.json`保留第二轮completed回执。 / Original failure, cancellation and successful completion are retained separately.
- `live-ledger-judgments.json`、`grounding-calls.json`为真实本地账本只读导出；`live-metrics.json`同时记录失败、成功和35项源码摘要核对。 / Read-only exports retain all decisions, grounding usage and source checks.
- `first-candidate-wire.json/png`为无网络重建；`inspect_target_check_wire.py`核对完整摘要。 / The wire files are explicitly offline reconstructions.
- 第二轮最终PNG位于session的 `runtime-output/local-direct-steps/local-step-0168f7a71b2945f0b5ab49a9b57ce608/observations/`，SHA256为 `947170926a02858f759b0fa7889c843cbda1ce32bf3d5d742adc943d58f9a1b6`。 / Original final screenshot and hash retained.
- `90-close.json`确认仅本轮新建窗口正常关闭，`99-finish.json`为cleanup_verified=true，runner退出0；35项冻结源码摘要无变化。 / Owned window closed normally; host cleanup verified; selected source hashes unchanged.
- 资料目录 `D:/AgentGUI-Projects/test-profiles/amadeus-codex-runtime-edge`保留，未清理缓存或改日常浏览器资料。 / The named test profile is retained; no browser-data cleanup or everyday-profile changes.

只读汇总器最初未处理页面action=null，首次汇总失败；已在测试脚本中改用空字典并重读原件成功，未重发API或动作。首败wire重建初次漏step/budget导致摘要断言失败，补齐原参数后通过；未改生产逻辑或原结果。 / Two analysis-script defects were corrected using retained data only; neither caused model/action redispatch or production changes.

本轮只执行真实验收和只读证据审计，未修生产逻辑、构建安装包、发布或宣称完整独立验收通过。后续优先用保留的误拒样本作受控诊断，并调查复核超时；再检查同一冻结候选连续完成，而非放宽阈值掩盖失败。 / No production fixes, builds or release were performed. Next investigate the retained false rejections and secondary timeout before claiming continuous stability.
