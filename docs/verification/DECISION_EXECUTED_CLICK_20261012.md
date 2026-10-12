# 历史点击图与原图对照 / Executed-click evidence comparison

## 范围 / Scope

用户批准将真实历史点击坐标标注接入正式 Decision 请求，再追加“只发标注图”的节省 token 对照。本轮只读取已保留的三张误拒案例及原始点击回执，不操作桌面，不修改浏览器资料、缓存或旧账本，不改变 Choice 语义问题或阈值。 / The user approved production original-plus-annotation wiring and then an annotated-only comparison. This slice replayed retained evidence only; no desktop, browser-data, ledger, semantic-question or threshold changes.

未发布源码的纯视觉字段核验（焦点、选区、输入值）会从真实完成的点击回执提取点；核对窗口身份、屏幕映射、按下/抬起坐标、原回执摘要和原图尺寸/摘要。provider 从原图在内存生成空心点标记，不接受外部标注位图，不改原文件。现有原图和细节裁剪仍发送，只在同一个请求内增加标注图，不增加模型调用。旧无物理坐标回执不伪造标记，native 路线不增加此字段。 / Unreleased pure-visual field checks derive the historical point from completed physical input. Identity, mapping, down/up coordinates, receipt and original-image bindings are checked. The provider renders the annotation in memory, preserving originals and existing crops within one request. Legacy coordinate-less receipts and native routes retain their prior behavior.

标注只是“此前点击过这里”，不是当前焦点、当前鼠标位置、成功或执行许可。 / A marker identifies a historical click, not current focus/cursor, success or authority.

## 固定样本结果 / Fixed-sample results

三组各8次请求，总计24次，无失败重试。三个预期满足案例每组各重放2次；两个故意错误的 expected-text 反例各1次。反例沿用真截图、真点击，只改变诊断期望，不伪造成真实输入回执。单图组仅在诊断 client 中去掉未标注原图和裁剪，并相应修改图片说明；Choice questions 逐字保持不变。生产默认仍是双图方案。 / Each arm used eight requests: two replays of each positive and one of each deliberately wrong expected-text control. There were 24 calls and no retries. Annotated-only transport is diagnostic, removing originals/crops and adapting image explanations while preserving the exact Choice questions. Production defaults remain original plus annotation.

| 案例 / Case | 原图＋原细节 / Original + detail | 加标注图 / Plus annotation | 仅标注整图 / Annotated only |
|---|---|---|---|
| 空搜索框选区检查 / Empty search selection | 不满足 2/2 | 不满足 2/2 | 满足 2/2 |
| 正确输入 java / Correct java value | 不满足 2/2 | 满足 2/2 | 满足 2/2 |
| 正确输入 Google URL / Correct URL value | 不满足 2/2 | 不满足 2/2 | 不满足 2/2 |
| java 画面、期望 python / Wrong expected query | 正确拒绝 1/1 | 正确拒绝 1/1 | 正确拒绝 1/1 |
| Google URL 画面、期望 example.com / Wrong expected URL | 正确拒绝 1/1 | 正确拒绝 1/1 | 正确拒绝 1/1 |

| 同样8次请求 / Same 8 requests | Original + detail | Plus annotation | Annotated only |
|---|---:|---:|---:|
| input_tokens 总计 / Total | 27,944 | 49,175 | 28,971 |
| HTTP 用时中位数 / Median | 211.4 ms | 250.6 ms | 224.7 ms |

单图比双图减少41.1%输入token；相比此前无标注方案则增加3.7%。HTTP时间不包含截图、定位、绘图或整个任务，不能当端到端提速；这也不是账单金额测量。输出token均为0；未观察到上报的缓存token。 / Annotated-only input tokens fell 41.1% versus dual-view, but rose 3.7% versus the original unmarked path. HTTP timings exclude capture, grounding, rendering and the full task; no end-to-end or billed-cost claim is made.

单图改善了这三个误拒案例中的两例；不能据此声称整体准确率或连续运行稳定。空字段选择尤其接近边界：met/not_met/insufficient=0.36/0.33/0.31，confidence=0.04；按既有 Choice 规则继续，不用概率重新否决。URL误拒仍未解决，未修改条件去强迫通过，未重跑完整浏览器任务。 / Two of the three retained false refusals improved with annotated-only evidence, without general accuracy/reliability claims. Empty-field classification remains marginal (0.36/0.33/0.31, confidence 0.04), routed by the existing Choice policy. URL refusal remains unresolved; no criteria weakening or complete desktop rerun occurred.

## 回归与证据 / Verification and evidence

Main最终离线回归：456 passed in 21.42s，覆盖新标注、真实请求体、认证不重绘、旧原图请求、前置候选标注、视觉字段、Choice、部分输入与Main交接。首轮新集成测试有3项因测试缺少正常review_context而跳过；补齐fixture后196项通过，再完成456项整合。计数重叠，不累加。独立只读审查检查了同批增量。 / Main final offline regression:456 passed in21.42s. Three initial fixture failures lacked normal review context; corrected fixtures passed196 checks before the final456. Counts overlap. A separate read-only review covered the increment.

维护源码：`app/judgment/executed_click_annotation.py`、`evidence.py`、`openai_decisions.py`、`service.py`、`app/execution/visual_field_proof.py`。 / Maintained source paths are listed here.

本地原始证据在 `.superpowers/sdd/2026-10-12-choice-runtime/`： / Local raw evidence:

- `executed-click-final.xml`：最终Main结果 / final Main regression.
- `executed-click-ab/{plan,results,marked-only-plan,marked-only-results,summary}.json`：预设方案、完整回复与usage / fixed plans, raw replies and usage.
- 各 `*-original`、`*-annotated`、`*-marked-only` 目录的 `prompt-and-images.md`：实际输入图与提示词 / exact input images and prompts.
- `click_ab_probe.py`、`click_only_probe.py`：不触碰桌面的诊断脚本 / screenshot-only diagnostic scripts.

未提交、推送、打包或热更新现有宿主。 / No commit, push, build or existing-host reload.
