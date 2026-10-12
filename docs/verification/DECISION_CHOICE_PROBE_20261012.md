# Decision Choice 固定截图对照 / Fixed-image Choice probe

2026-10-12，诊断实验，不是发布或桌面验收。 / Diagnostic experiment, not a release or desktop acceptance.

用户要求尝试 Decision 的直接选择。使用既有独立浏览器测试中保存的截图，先经项目 `prepare_request` 验证图像摘要和会话归属，再用当前 provider 的 MockTransport 捕获实际请求正文。真实测试不加载执行宿主、不产生输入、不修改原 Decision 账本、阈值或浏览器资料。 / The user requested direct Choice decisions. Existing isolated-browser screenshots were validated through `prepare_request`; MockTransport captured the current provider's actual request body. Live inference did not start an executor, dispatch input, mutate historical ledgers or thresholds, or touch browser profiles.

## 方法 / Method

- 六个固定案例，每个分别调用 predicate 与 choice，一共十二次真实 `gpt-6-luna /v1/decisions` 请求；每例只调用一次各方案，顺序交替，无失败重试。 / Six fixed cases, two arms each, twelve real requests; one sample per arm, alternating order, no retries.
- 两方案保持图像、局部图、`auto` 图像细节、当前条件、`visible_error` 和 `needs_agent_review` 问题相同；只把第一个问题改成 `condition_met / condition_not_met / evidence_insufficient` 三选一及对应分类说明。 / Identical images, crops, auto detail, current criteria and auxiliary questions; only the first question changes to the three-way Choice classification and its option descriptions.
- predicate 按现有本步通过阈值 0.80 对照；Choice 表格展示直接返回的选项，不套用该阈值，不授权动作。两类分数不可直接等同。 / Predicate comparison uses the existing 0.80 step threshold; Choice reports its selected label without applying that threshold or authorizing actions. Scores are not interchangeable.
- 预期标签由 Main 目视原截图判断，不是独立人工标注集。四个正确状态和两个反例有意用于诊断；没有覆盖真实证据不足、遮挡、错焦点、部分选中等全部边界。 / Expected labels are Main's visual assessment, not independent human annotations. Four positive states and two counterfactual negatives form a diagnostic sample, lacking comprehensive insufficient-evidence, occlusion, wrong-focus and partial-selection coverage.
- 反例只改变问题：Google 网址要求匹配 Bing；Google 空白首页要求已经显示 java 搜索结果。未修改原图，也未伪造原历史记录。 / Negatives change only the requested criterion: Google URL versus expected Bing, and Google home versus expected java results. Pixels and historical records are untouched.

## 结果 / Results

| 案例 / Case | Predicate | Choice | 选中项概率 / Selected probability | confidence |
|---|---:|---|---:|---:|
| 地址栏文字全选 / Address selection | .95，通过 / pass | condition_met | .79 | .69 |
| 地址栏焦点 / Address focus | .14，未通过 / withheld | condition_met | .46 | .19 |
| 空搜索框替换准备 / Empty search replacement | .65，未通过 / withheld | condition_met | .57 | .35 |
| 地址栏输入值 / Address value | .94，通过 / pass | condition_met | .86 | .79 |
| 错误期望网址 / Wrong expected URL | .00，不通过 / fail | condition_not_met | .98 | .97 |
| 未出现 java 结果 / Missing java results | .00，不通过 / fail | condition_not_met | .95 | .93 |

所有辅助问题 `visible_error=0`；错误网址的 `needs_agent_review=.18`，其余为零，两个方案相同。 / All auxiliary visible-error scores were zero. Wrong-URL review scored .18, all other review scores zero, identically in both arms.

Choice 在这六例中的选择均符合 Main 的预期；不能由此宣称准确率 100% 或稳定优于 predicate。地址栏焦点的三个选项概率为 .46/.28/.26，直接选择只是相对最高，仍存在明显不确定性。该实验同时改变了结果表示与采用规则，消除两次阈值阻止不等于感知准确性已经提高。 / All six Choice labels match Main's expectations, not proof of 100% accuracy or general superiority. Address focus had .46/.28/.26 probabilities: the winner is only relatively highest. The comparison changes result representation and adoption policy, so avoiding two threshold stops does not establish improved perception.

HTTP 整体用时：predicate 中位数 221.89 ms，范围 218.78–242.10 ms；Choice 中位数 227.84 ms，范围 211.34–285.71 ms。总输入/总 tokens 53,548，输出为零。样本量小、同图请求可能命中缓存，不能推出冷启动或端到端提速。 / HTTP elapsed median/range: predicate 221.89/218.78–242.10 ms; Choice 227.84/211.34–285.71 ms. Total tokens: 53,548, zero output tokens. Small repeated-image samples may benefit from caching and do not establish cold-start or end-to-end improvement.

## 证据与状态 / Evidence and status

- 脚本 / Script: `.superpowers/sdd/2026-10-12-decision-choice/choice_probe.py`
- 本地请求与来源 / Local prepared bodies and sources: `prepared.json`, `manifest.json` in the same directory.
- 派发与原始响应 / Dispatch markers and raw responses: `dispatches.jsonl`, `results.json` in the same directory.
- 实际命令 / Executed: `python -B -X utf8 .superpowers/sdd/2026-10-12-decision-choice/choice_probe.py prepare`, then `... live`; both exit 0.
- 现有生产适配器仍是 predicate-only；本实验未把 Choice 伪装成 probability=1，也未接入真实动作放行。 / The maintained provider remains predicate-only. Choice was not converted to a fabricated probability of one or connected to action admission.
- 下一步：固定分类契约，扩充有独立标注的困难反例与证据不足样本，评估误放/误拒及接管率，再决定运行时采用规则；原生/UIA整改与已中断修改的验收状态不因本次实验改变。 / Next: freeze the classification contract, expand independently annotated hard negatives and insufficient-evidence cases, measure false acceptance/rejection and takeover, then decide runtime adoption. This probe does not complete interrupted runtime work or native/UIA validation.

官方接口 / Official interface: [Create a decision](https://developers.openai.com/api/reference/resources/decisions/methods/create). Choice 返回选项、confidence 和各选项 probabilities，不是无置信信息的硬判断。 / Choice returns a label, confidence and per-option probabilities.
