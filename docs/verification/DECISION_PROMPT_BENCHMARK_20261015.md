# 2026-10-15 Decision 提示词比较 / Decision prompt comparison

本轮 Primary 保留集的三分类精确匹配由 **148/160（92.5%）变为152/160（95.0%）**，但 pass/nonpass 二分类均为 **152/160（95.0%）**，误放、误拒均未减少。后续两级回放两组均为 **149/160（93.125%）**，未证明级联整体准确率提升。仅选择 `page_result`、`text_value` 的简短 instructions；`graphic`、`input_field` 保持原问法。这个有限结果不证明减少 Main 接管、提高通用安全性或加快完整执行流程。

Primary held-out exact three-way matches changed from **148/160 (92.5%) to 152/160 (95.0%)**. Both strategies scored **152/160 (95.0%)** after collapsing answers to pass/nonpass, with unchanged false accepts and false rejects. Subsequent cascade replay scored **149/160 (93.125%) for both**, without demonstrating an overall cascade accuracy gain. Only the short `page_result` and `text_value` instructions were selected; `graphic` and `input_field` retain their baseline wording. This limited result does not demonstrate fewer Main handoffs, general safety gains or faster complete workflows.

## 样本与标注 / Dataset and annotation

套件 `real-gui-20261015-v2` 包含 **39 张真实原图、30 个界面族、254 个案例**，覆盖公开网页及低风险桌面界面。标签由 AI 初标、Main AI 复核，**不是人工真值**，也不以被测模型输出作为真值。原图来源按保留的标注来源记录归属，本报告不独立认证所有原始采集过程。

The suite contains **39 real source images, 30 interface families and 254 cases**, covering public webpages and low-risk desktop interfaces. Labels were initially annotated by AI and reviewed by Main AI; **they are not human ground truth** and were not defined from the evaluated model's answers. Source attribution follows the retained annotation provenance; this report does not independently certify every original capture process.

| 分类 / Category | 唯一案例 / Unique cases | 判断范围 / Judgment scope |
| --- | ---: | --- |
| `input_field` | 56 | 标记中心是否在指定输入框内 / Marker-center containment in the named input field |
| `graphic` | 95 | 标记处图形、菜单或链接是否符合目标 / Marked graphic, menu item or link matches the target |
| `page_result` | 75 | 当前可见页面是否显示指定结果 / The visible page shows the specified result |
| `text_value` | 28 | 字段内已输入文字是否符合规定内容 / Entered field text matches the specified content |

标签总计125 个 `condition_met`、123 个 `condition_not_met`、6 个 `evidence_insufficient`。样本包含真实错误控件、相邻菜单/链接、网页内嵌软件宣传图和错误文字等反例。证据不足样本很少，不能据此评价广泛遮挡、模糊或不可读场景。

Labels comprise 125 `condition_met`, 123 `condition_not_met` and 6 `evidence_insufficient` cases. Negative examples include real wrong controls, adjacent menu items/links, embedded software illustrations and incorrect text. Insufficient-evidence cases are scarce, limiting conclusions about occlusion, blur and unreadable scenes.

## 分集与冻结 / Splits and freezing

按 `group_id` 界面族分集，同族及相近布局不跨训练、验证、保留集；**不按宿主会话宣称独立**。多个族可能共用采集会话，同图多个案例及重复请求也存在相关性。254 个案例不是254 个独立场景，保留集的160 次回答也不是160 张独立截图。

Splits use interface-family `group_id`, keeping the same family and closely related layouts together. **Host sessions are not treated as independent experimental units.** Families can share capture sessions; cases from the same image and repeated requests are correlated. Neither 254 cases nor 160 held-out answers represent that many independent scenes.

| 阶段 / Stage | 界面族 / Families | 唯一案例 / Unique cases | 策略与重复 / Strategies and repeats | Primary 请求 / Requests |
| --- | ---: | ---: | --- | ---: |
| Train | 13 | 104 | baseline、region_first、short，各1次 / Once each | 312 |
| Validation | 8 | 70 | baseline、训练冻结组合，各2次 / Twice each | 280 |
| Test | 9 | 80 | baseline、最终冻结组合，各2次 / Twice each | 320 |
| 合计 / Total | 30 | 254 | — | **912** |

比较计划先固定 seed=`20261015`、分集和任务顺序。训练集按分类选择：精确准确率降序，随后误放、误拒、HTTP 中位耗时、输入 token 升序；完全同分保留 baseline。训练选择为 graphic=baseline、input_field=region_first、page_result=short、text_value=short。验证集允许否决分类改动：input_field 未带来准确率/误放/误拒改善，且 token 与耗时未获益，因此回到 baseline；其余保留 page_result/text_value。最终组合在读取 test 结果前冻结，`final-selection.json` 记录 `stage=frozen_before_test`、`test_results_read=false`，冻结时间为 `2026-10-14T14:51:59.759529+00:00`。

The comparison plan fixed seed=`20261015`, splits and task order in advance. Training selected per category by exact accuracy, then fewer false accepts, fewer false rejects, lower median HTTP latency and fewer input tokens; a complete tie retained baseline. Training selected baseline graphics, region-first fields and short page/value questions. Validation rejected the field change because it offered no accuracy/error benefit and no token or latency benefit. The final page/value-only mix was frozen before test results were read; its selection record stores the pre-test stage, unread-test flag and UTC timestamp above.

冻结的采纳规则要求保留集精确准确率不降低，误放、误拒、错误和未知用量不增加，并至少有一项实测收益；不通过则保留 baseline，**不在 test 上改写提示词、回调阈值或重新挑选组合**。本轮满足该描述性采纳规则，不等同统计显著性或通用产品验收。

The frozen adoption rule required no decrease in held-out exact accuracy, no increase in false accepts/rejects, errors or unknown usage, and at least one measured benefit. Failure would retain baseline, **without rewriting prompts, retuning thresholds or selecting another mix on test**. Passing this descriptive rule is not a significance claim or general product acceptance.

## 比较方法 / Comparison method

使用固定请求清单交错发送 baseline 与候选，模型为 `gpt-6-luna`，Primary endpoint 为 `/v1/decisions`，单次 HTTP 时限8秒。实验变量是分类对应的 `question.instructions`；选择项、图像协议、目标及期望文字、解析规则和运行时安全门禁不因本轮选择而放宽。期望标签留在本地评分，不发送为答案提示。912 次 Primary 请求全部完成，请求/协议错误、超时和未知用量均为0；保留的原始回答、choice、usage及摘要由 Main 审核。

Frozen request manifests interleaved baseline and candidate calls to `gpt-6-luna` through `/v1/decisions`, with an 8-second HTTP deadline. The experimental variable was the category's `question.instructions`; choices, image protocol, targets/expected text, parsing and runtime safety gates were not relaxed. Expected labels remained local to scoring. All 912 primary requests completed with zero request/protocol errors, timeouts or unknown usage; Main audited retained replies, choices, usage and summaries.

精确准确率按三种标签完全匹配计算。误放是负例/证据不足被回答为 `condition_met`；误拒是正例被回答为非通过。`errors` 指请求/协议错误，分类答错另计；错误仍计入准确率分母，不当作正确负例。二分类只把 `condition_met` 视作 pass，其余两类视作 nonpass。confidence/probabilities 不用于本轮重新设定采用阈值。

Exact accuracy requires the correct one of three labels. A false accept returns `condition_met` for a negative or insufficient-evidence label; a false reject returns nonpass for a positive. The metric `errors` refers to request/protocol failures, distinct from classification mistakes. Such failures remain in the accuracy denominator and are never counted as correct negatives. Binary scoring treats only `condition_met` as pass. Recorded confidence/probabilities were not used to retune adoption thresholds.

`text_value` 使用生产问法与字段裁图协议建立题目，**不是完整 compact 生产 wire 的逐字节重放**，也不是已执行输入的认证回执。静态 page_result 只能评价当前可见结果，不能证明持续加载、隐藏状态、保存持久性或真实应用已经启动。

The `text_value` cases use the production question and field-crop protocol, **not a byte-for-byte replay of the complete compact production wire**, nor an authenticated receipt of executed input. Static page questions cannot establish temporal progress, hidden state, durable saving or an actual application launch.

## 结果 / Results

| 阶段 / Stage | 比较顺序 / Strategy order | 精确匹配 / Exact matches | 误放 / FA | 误拒 / FR |
| --- | --- | --- | ---: | ---: |
| Train | baseline / region_first / short | 98/104 / 95/104 / 96/104 | 3 / 5 / 3 | 3 / 4 / 4 |
| Validation | baseline / train-frozen mix | 134/140（95.71%） / 136/140（97.14%） | 2 / 2 | 2 / 2 |
| Test | baseline / final-frozen mix | **148/160（92.50%） / 152/160（95.00%）** | **4 / 4** | **4 / 4** |

训练行比较三个完整问法，不能把分类组合的选择写成某个完整问法整体获胜；验证候选仍包含后来被否决的 input_field 改动，test 才是最终组合。各阶段不能合并成一个无偏准确率。

The training row compares three complete variants and does not show an overall win for either alternative. Validation still tested the field change that was subsequently rejected; test evaluated the final mix. The stages must not be pooled into one unbiased accuracy estimate.

| 保留集分类 / Held-out category | 唯一案例 / Unique cases | Baseline | 最终组合 / Final mix |
| --- | ---: | ---: | ---: |
| `graphic` | 33 | 62/66 | 62/66 |
| `input_field` | 16 | 30/32 | 30/32 |
| `page_result` | 23 | 44/46 | 46/46 |
| `text_value` | 8 | 12/16 | 14/16 |

四次新增正确回答仅来自两个案例各重复两次：网页内嵌 Writer 编辑器宣传图不能证明真实 Writer 窗口已打开；空白文档不符合规定输入文字。两案均从 baseline 的 `evidence_insufficient` 改成正确的 `condition_not_met`。**没有 pass/nonpass 翻转**，因此二分类两者都是95%，不能称本轮减少拒绝、普通复核或 Main 接管。

The four additional exact matches came from just two cases, repeated twice each: an embedded Writer illustration did not establish a real Writer window, and a blank document did not contain the specified text. Both changed from baseline `evidence_insufficient` to the correct `condition_not_met`. **No pass/nonpass answer changed**, so both binary accuracies remained 95%; this does not demonstrate fewer refusals, secondary reviews or Main handoffs.

误放反例仍然存在：两个 graphic 案例把相邻的 Format 菜单项当作 Edit、把相邻 Signatures 链接当作 Releases，各重复两次，合计4次误放；正例的4次误拒也保留。当前第一层通过会跳过普通复核，所以这些 Primary 误放不能假定会被第二层纠正。少量相关案例、AI 标签及稀少的证据不足样本，不支持通用误放率或安全性改善结论。

False accepts persisted: two graphic cases confused an adjacent Format menu item with Edit and a Signatures link with Releases, twice each. Four false rejects also remained. A primary pass currently bypasses ordinary review, so these false accepts cannot be assumed corrected by the second stage. Small correlated samples, AI labels and sparse insufficient evidence do not support general false-accept or safety-improvement claims.

## 用量与耗时 / Usage and latency

| 保留集指标 / Held-out metric | Baseline | 最终组合 / Final mix |
| --- | ---: | ---: |
| 输入 token / Input tokens | 179,196 | 176,260（−2,936；**−1.64%**） |
| 输出 token / Output tokens | 0 | 0 |
| HTTP p50 | 181.86505 ms | 175.90005 ms |
| HTTP p95 | 299.9909 ms | 314.9071 ms |
| 错误 / Errors；未知用量 / Unknown usage | 0；0 | 0；0 |

以上仅为该批次 HTTP 耗时：p50 较低而 p95 较高，不能称整体稳定提速。它不含截图、定位、图像编码、普通复核、窗口准备、动作派发、页面等待或清理。三阶段提示词比较共1,084,403 个输入 token、0 个输出 token；统一预算当时 spent=1,206,631、reserved=0，还包含此前流程调用，不能把总账差额都归给提示词实验。

These are batch-specific HTTP timings: lower p50 and higher p95 do not establish a consistent speedup. They exclude capture, grounding, encoding, secondary review, window preparation, input, page waits and cleanup. The three prompt stages used 1,084,403 input tokens and zero output tokens. The unified ledger then showed 1,206,631 spent and zero reserved, including earlier workflow calls; its entire balance must not be attributed to this prompt experiment.

## 采纳边界与完整级联回放 / Adoption boundary and completed cascade replay

本轮只选择 `page_result`、`text_value` 的 instructions。候选定位、标图/裁图、choices、解析与认证、输入授权、取消/期限、请求上限、普通Luna同图同问复核及返回原 Main 的合同保持原样；不因测试结果降低门禁或回调阈值。本报告不代表安装器已经更新。

Only page-result and text-value instructions were selected. Grounding, marked/cropped images, choices, parsing/authentication, input authorization, cancellation/deadlines, request caps, same-image/same-question ordinary Luna review and return to the original Main retain their contracts. No test-driven gate or threshold relaxation is justified. This report does not imply an updated installer.

**`cascade-test-01` 已完成。** 它复用已冻结的320 条 test Primary 回答，对每组82 条非通过回答各发一次普通 Luna 复核，共 **164 次新增 Secondary 请求**，全部完成、无请求/协议错误或未知用量。Primary 通过仍直接沿用，不触发复核。Main 的 `cascade-audit-main.json` 重新核对了320 条 Primary 绑定、164 份 Secondary 原始请求/raw SHA、解析、usage及逐例耗时相加；本文另只读回核164 份原始回答的 choice/usage/SHA与汇总。

**`cascade-test-01` is complete.** It reused the 320 frozen test primary answers and issued one ordinary Luna review for each nonpass: 82 per strategy, **164 new secondary requests**, all completed without request/protocol errors or unknown usage. Primary passes still bypass review. Main's cascade audit reconstructed all 320 primary bindings, 164 secondary request/raw hashes, parsing, usage and per-case latency sums. This report additionally checked the 164 raw answers' choices, usage, hashes and aggregates without new requests.

| 两级回放指标 / Cascade replay metric | Baseline | Frozen mix |
| --- | ---: | ---: |
| 三分类精确匹配 / Exact three-way | 149/160（93.125%） | 149/160（93.125%） |
| pass/nonpass 二分类 / Binary | 151/160（94.375%） | 152/160（95.0%） |
| 最终误放 / Final FA | 8 | 7 |
| 最终误拒 / Final FR | 1 | 1 |
| 纠正原4次误拒 / Original FR corrected | 3/4 | 3/4 |
| 新增误放 / New FA from review | 4 | 3 |
| Secondary 请求 / Requests | 82 | 82 |
| Primary＋Secondary token（含输入输出） / Tokens, both stages | 292,419 | 287,841 |
| 逐例 HTTP 和 p50 / Per-case HTTP sum p50 | 1,089.2886 ms | 1,152.47605 ms |
| 逐例 HTTP 和 p95 / Per-case HTTP sum p95 | 2,772.488 ms | 2,672.4098 ms |

两组各纠正3次原有误拒，但分别新增4/3次误放。新组合从第一层精确95%降到两级93.125%；二分类虽仍为95%，错误构成已由4误放＋4误拒变为7误放＋1误拒。不能把纠正次数单独当作整体提升，也不能据此声称减少 Main 接管或改善安全性。旧组合的精确匹配略增，但二分类从95%降至94.375%，同样不是一致改善。

Each strategy corrected three original false rejects but introduced four/three false accepts. The frozen mix fell from 95% primary exact accuracy to 93.125% after review. Its binary score stayed 95%, while errors shifted from 4 FA + 4 FR to 7 FA + 1 FR. Correction counts alone do not show an overall gain, fewer Main handoffs or better safety. Baseline exact accuracy rose slightly while its binary accuracy fell from 95% to 94.375%, also a mixed result.

| 可审计反例 ID / Auditable case ID | 回放结果 / Replay outcome |
| --- | --- |
| `b15-graphic-04`、`d11-graphic-04` | 两组均保留各2次 Primary 误放，未触发复核 / Both retain two false primary passes per case, without review |
| `b15-field-02` | 两组复核都把菜单栏误当编辑字段，分别新增2次误放 / Review adds two false accepts per strategy by treating a menu item as an editing field |
| `c08-field-site-search-wrong-control` | Baseline 新增2次误放：地址栏不是网页搜索框 / Baseline adds two false accepts: browser address bar versus page search field |
| `libreoffice-embedded-editor-decoy` | Frozen mix 的两次正确 Primary 否定分别变成误放、证据不足 / Two correct frozen-mix negatives become one false pass and one insufficient answer |
| `b15-value-06` | Frozen mix 两次正确否定均被改为证据不足；仍属 nonpass，但精确标签退化 / Two correct negatives become insufficient; binary outcome stays nonpass but exact labels regress |
| `a04-field-address-in`、`b15-value-05` | 每组纠正地址栏1次、空白值正例2次；地址栏仍各剩1次误拒 / Each corrects one address-bar and two blank-value positives; one address-bar false reject remains per strategy |

这不是同一实机连接中即时连续运行两层：Primary 使用既有冻结回答，Secondary 随后单独执行。因此 HTTP 指标先逐例把两次请求耗时相加再取分位数，**不是实际整步 wall time**，也不验证实机整步时限、连接复用或 Main 调度。复核使用相同题目/图像协议，期望真值不发送给模型；`text_value` 的 factory/裁图比较仍受前述非完整 compact wire 的限制。

This was not an immediate two-stage live run on one connection: cached primary answers were followed by separate secondary execution. HTTP percentiles are computed after adding each case's two request durations, **not from actual step wall time**. They do not validate runtime deadlines, connection reuse or Main scheduling. Review uses the same question/image protocol without sending truth labels; the text-value factory/crop comparison retains the incomplete-compact-wire limitation above.

Secondary 新增223,660 输入＋1,144 输出＝**224,804 token**；没有重记已完成 Primary 的费用。只读重算统一 journal 得到截至本轮的全目标 **spent=1,431,435、reserved=0、未知=0**。两组表中的总 token 包含已完成 test Primary，不能再次与总账相加。按既有要求，已知误放防护本轮暂缓，保留原 Decision→普通 Luna→Main 架构；不针对这些 test 反例改提示词、阈值或增加回调。

Secondary execution added 223,660 input + 1,144 output = **224,804 tokens**, without recharging completed primaries. A read-only journal recomputation gives whole-goal **spent=1,431,435, reserved=0, unknown=0** at this checkpoint. The table's per-strategy totals already include test primaries and must not be added again to the ledger. False-accept protection remains deferred as previously required; the original Decision→ordinary Luna→Main architecture is retained, without test-driven prompt/threshold changes or added callbacks.

## 冻结证据 / Frozen evidence

以下为保留证据中的文件名与 SHA256；只公开统计和摘要，不附原图、私有配置、原始用户数据或大段请求/回答。 / Retained evidence is identified by filename and SHA256 below. Only aggregate results and hashes are published; original images, private configuration, raw user data and large request/reply payloads are omitted.

| 文件 / File | SHA256 |
| --- | --- |
| `suite-v2/suite.json` | `577ec133b92fcdac077be541491403e537acb96ec46baa32f054cca96cdcf672` |
| `comparison-plan.json` | `60a472a237f177e9e31680393b660ea47991e4e6a97d7cebf5f935464041d72f` |
| `frozen-selection.json` | `f6cfb1ce6bf5054db0cfe32bcefb9d37b3a5f1ff41a4c78008bb3ea40aebf9bc` |
| `final-selection.json` | `2d20d77f39f160633629f3732591918007cfcc82fab9c84644b0c387d18301d1` |
| `heldout-audit-main.json` | `ed8000aeff6c4eb6e5affd83f2993e746eafa0c2ac2aec775c0409ccfd617722` |
| `train-run-01/summary.json` | `cd9dd84e74318fc742f1e944beada6ab2a7e56dc797a829db6bd06c7c9cc5a57` |
| `validation-run-01/summary.json` | `bd4f14902cf7e8ee57d8ed1af67a5cea795b9e5817877230a2f15ee7c524fc9c` |
| `test-run-01/summary.json` | `ff417fedf1388160ff10fa96828875bc27bf82a91e9441c1853871f032c21c42` |
| `cascade-test-01/summary.json` | `744e6b2e6229bd08b1dc2bcd3c051c97dc8a640b5b1e9ede9dc8699814625c60` |
| `cascade-test-01/results.json` | `a9b42518a9d22251cd09c824f467deb540716f65915e5c58d63dbfb4abd80627` |
| `cascade-audit-main.json` | `e7054d1b132093b847a9fd160cf300b766b788e3b435c65388d0c6d2f5cbd21f` |
