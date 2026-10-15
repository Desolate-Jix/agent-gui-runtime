# 两级判断真实 API 重放 / Live cascade replay

**复核限定 / Audit qualification:** 本轮未原样复现之前10/10的符号分类问题，旧/新Luna请求也同时改变多个因素；自动第二层零覆盖。下表仅记录这些具体请求的结果，不能用于判定两级架构或模型总体能力。原始数值保留。[完整复核](DECISION_CASCADE_AUDIT_20261014.md)。 / The earlier symbol classifier was not reproduced unchanged, multiple prompt variables changed, and no automatic secondary branch ran. These counts do not establish general cascade/model efficacy.

2026-10-14。结论：本轮未显示准确率提升。自然两级路线正确5/10，第一层对两张图均选择通过，普通复核触发0次；显式旁路调用同提示词普通Luna正确2/10。 / No measured accuracy improvement: the natural cascade was correct on 5/10 trials, with zero second-stage calls because Decision passed both images. An explicitly separate ordinary-Luna diagnostic scored 2/10.

## 对比 / Comparison

所有组为相同两张静态裁剪标注图，各5次。图片字节相同，问题/上下文不同，旧组不是本轮交错A/B；网络、缓存与首连接均可能影响速度。只选＋/×的组是更窄的二分类问题，不能当作通用GUI准确率。 / Same two images, five repetitions each; bytes match exactly, but prompts/context differ. Historical runs were not interleaved with this run. The symbol-only task is narrower than target suitability.

|方案 / Route|正确 / Correct|10次HTTP等待合计 / Total s|单次HTTP中位数 / Median s|输入token / Input|输出token / Output|
|---|---:|---:|---:|---:|---:|
|之前 Decision：目标是否匹配 / Previous target-match Decision|5/10|4.821|0.344|8,910|0|
|之前普通 Luna：同一旧问题 / Previous ordinary Luna|9/10|20.600|1.979|9,940|66|
|之前 Decision：直接选＋/× / Previous direct symbol Choice|10/10|2.479|0.224|8,280|0|
|本轮自动两级路线 / Current natural cascade|5/10|4.090|0.244|10,880|0|
|本轮普通 Luna 单独诊断 / Current direct Luna diagnostic|2/10|22.474|2.224|11,970|65|

本轮自动路线服务总耗时：10次合计 **5.550秒**，单次中位数 **0.385秒**，包括证据读取/渲染、API等待、认证持久化及诊断记录。HTTP等待另计为上表口径；此前实验未记录同口径服务总时间。不是浏览器动作时间或主Agent响应时间。 / Current service elapsed includes preparation, HTTP, persistence and diagnostic recording; old runs lack this end-to-end metric. It is not GUI action or Main scheduling latency.

## 逐类结果 / Per-case results

|样本 / Case|目标 / Target|自动两级 / Natural cascade|普通Luna独立诊断 / Direct Luna|
|---|---|---|---|
|标记位于＋ / Marker on plus|新建标签＋ / New Tab plus|5/5正确，全部通过 / All pass|1/5正确，4次误拒 / Four false refusals|
|标记位于× / Marker on cross|仍要求新建标签＋ / Still New Tab plus|0/5正确，5次误放 / Five false passes|1/5正确，4次误放 / Four false passes|

第一层没有非通过，因此两级收益在这组图上没有机会发生。普通Luna单独结果不替换或美化自然路线得分，也不能据此宣称双层链路在真实API下跑通。新提示词虽要求先看图形，仍返回目标匹配选择；与此前直接输出＋/×不是同一种问题。 / No first-stage nonpass occurred, so the cascade never entered stage two. The diagnostic score does not replace the natural-route score or prove a live two-stage traversal. Graph-first wording remains a target-match choice, not direct symbol classification.

## 首败、修复与验证 / Initial failure, repair and verification

- 首次普通响应内容正确，但合法 `phase: final_answer` 被字段白名单拒绝：`ordinary_review_message_invalid`。原始响应和HTTP时间保留。 / The first ordinary response was valid but its final-answer phase metadata was rejected.
- 最小修复位于 `app/judgment/openai_decisions.py`：接受缺省/null/final_answer，继续拒绝commentary、未知phase和额外答案。新增回归修前2失败/3通过；修后相关85项通过。 / The parser now accepts absent/null/final_answer only; 85 focused checks pass after reproducing the failure.
- 首次付费响应离线重解析，不重发；其后9次真实响应由修复后的provider正常接受。该2/10是原始模型答案准确率，首轮协议失败未改记为首次集成成功。首次服务总耗时丢失，故普通诊断仅用10次完整HTTP计时对比；9次服务时间另存。 / First response recovered offline without another charge; nine subsequent live responses parsed successfully. Raw-answer accuracy is distinct from initial integration success. The first service-total timing is unavailable; all ten HTTP timings remain available.
- 用户要求暂缓的误放缺陷 `DECISION-FALSE-ACCEPT-001` 未修，本轮仅补充真实失败证据；未改提示词、阈值、路由或浏览器数据。无桌面动作、无安装/发布。 / Deferred false-accept protection is unchanged; no prompt, threshold or routing change, desktop action, installation or publication.

本轮总调用 **20次**：自然Decision10次＋独立普通诊断10次；输入 **22,850 token**、输出 **65 token**。无重试。20个不同请求ID、图片哈希、返回值和用量已核对。 / 20 calls total, 22,850 input and 65 output tokens, no retries. Request identities, image hashes, answers and usages were audited.

## 证据 / Evidence

- `manifest.json`, `summary.json`, `*-assessment.json`, `*-request.json`, `*-response.json`, `*-http.json`：自然路线。
- `direct-luna-diagnostic/`：独立普通诊断、首败 `phase-fix.json`、原始/续跑脚本与响应。
- 旧组：同父目录 `decision-vs-luna-ab-20261014-01` 与 `decision-symbol-choice-20261014-01`。
- API phase参考 / API phase reference: https://developers.openai.com/api/reference/resources/responses/methods/create

两张重复图片的结果不代表通用准确率，也未测试遮挡、移动窗口、更多控件或实际点击。 / Two repeated images do not establish general accuracy, occlusion handling or live action reliability.
