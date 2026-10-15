# 两级实验复核 / Cascade experiment audit

2026-10-14。只读核对既有证据；没有新增API或桌面调用，没有修改模型路由。 / Existing-evidence audit only; no new API or desktop calls and no routing changes.

## 已确认的问题 / Confirmed experiment limitations

1. **成功基线没有被原样复测。** 上次10/10的Decision问题是直接选 `plus` / `cross`，本轮是 `condition_met` / `condition_not_met` / `evidence_insufficient` 的目标匹配。增加“先看图形”说明不等于直接图形分类。两种问题、选项数量和期望标签不同。 / The earlier 10/10 symbol classifier was not rerun unchanged. Graph-first wording inside a target-match question is a different task.
2. **旧/新普通Luna不是单变量对照。** 旧请求文字975字符，新请求2046字符；新增可用性/遮挡上下文、动作kind、空allowed_states，并改变问题序列化文本。图片相同不能证明其余输入等同。 / Ordinary-Luna text grew from975 to2046 characters while context and formatting also changed; identical images alone do not make a controlled comparison.
3. **没有真实覆盖第二层自动分支。** 十次Decision全部通过，所以本轮实际只执行第一层。额外十次普通Luna是显式旁路诊断，不能当作自动两级收益或实际第二层触发延迟。 / All ten first stages passed; the automatic secondary branch was never traversed. Separate direct diagnostics are not cascade acceptance.
4. **性能比较是历史批次，不是同期交错A/B。** 新Luna后八次各报告1194缓存输入token，旧Luna十次均报告0；服务总耗时与HTTP计时也不能混用。缓存差异已观察到，但没有证据证明缓存导致误判。 / Historical batches differ in caching and timing scope; cache counters do not establish an accuracy cause.

## 保留的事实 / Facts retained

Main 与独立复核均确认：20个记录请求的载荷哈希可重建一致；10个真实 Responses 经当前解析器离线重解析，答案与用量逐项一致。 / Main and independent audit reconstructed all20 recorded payload hashes; all10 actual Responses reparse offline with identical answers and usage.

- 图片人工查看与哈希核对一致：正例标记在＋，反例在×，目标始终是新建标签＋；未发现标签反置。 / Visible marker positions and hashes agree with the labels.
- 原始Decision响应十次均为 `condition_met`；原始Luna响应正例仅一次通过、反例仅一次不通过，因而样本答案计数确为5/10及2/10。这些不是把输出映射反了，也不能外推为模型通用准确率。 / Raw replies support the two observed counts; they do not establish general model accuracy.
- 模型、普通Luna推理none、32输出上限、default tier、temperature1、top_p0.98及无previous_response_id在旧/新组中一致。 / Those model/inference parameters match between batches.
- 第一个普通响应的合法 `phase: final_answer` 确曾触发解析白名单错误；后续离线恢复不改变其原始文本。首败不能冒充首次端到端成功。 / The phase allowlist failure was real; offline recovery preserved the original answer and is not first-attempt integration success.

## 结论修正 / Corrected interpretation

这次实验存在对照设计与分支覆盖问题，不能据此认定两级架构无效或普通Luna能力退化。可确认的是：本轮这组具体请求得到这些答案，而且未触发第二层。分数、计时和token原始记录保留，不修改为更好结果。 / The experiment cannot establish cascade ineffectiveness or a regression in general Luna capability. It establishes only the recorded outcomes for these requests, with no automatic second-stage traversal. Raw results remain unchanged.

正确的下一轮应先原样复现旧符号分类与旧普通Luna基线，再单独改变一个提示因素；真实非通过样本用于覆盖第二层接续。仅用模拟拒绝能验证代码路由，不能计入真实模型准确率。本次审核没有执行该新一轮。 / A future controlled rerun should reproduce both earlier baselines unchanged before changing one factor, and exercise the secondary route on genuine nonpass results. Injected refusals test code routing only. No such new run was performed during this audit.

Evidence / 证据：`D:/AgentGUI-Projects/evidence/amadeus-codex-runtime-2026-10-14/run-caa6cb09/decision-cascade-replay-20261014-01`，旧基线位于同父目录的 `decision-vs-luna-ab-20261014-01` 和 `decision-symbol-choice-20261014-01`。
