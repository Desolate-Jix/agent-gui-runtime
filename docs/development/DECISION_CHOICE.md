## Current target wording / 当前目标表达

`action.goal` 与 `field_goal` 只描述当前可见对象，保留所有必要限定条件；筛选条件和排序范围须明确。例如“主结果区中可见域名为 `curl.se` 的第一个匹配普通结果，排除广告与摘要卡片”，不同于“整个结果列表的第一条”。流程总目标放在 `plan.goal`，结果要求放在 `verification`，重试、接管与恢复规则由计划控制，不塞入目标语句。视觉定位和候选 Decision 使用同一目标；运行时不自动改写目标，也不使用模型候选名称代替目标。

Keep `action.goal` / `field_goal` to the current visible target while preserving every required qualifier. State filtering and ordering explicitly: the first matching ordinary result with visible domain `curl.se` differs from the first result overall. Put task objectives in `plan.goal`, expected outcomes in `verification`, and retry/recovery in plan controls. Grounding and candidate Decision receive the same target. The runtime does not rewrite it or substitute the candidate model label.

This is a caller-facing usage contract, not a semantic parser or additional model call. Frozen requests and prior failures remain unchanged. See [retained-image diagnosis](../verification/DECISION_TARGET_USAGE_20261013.md). / 这是调用契约，不增加语义解析器或模型请求，不改写冻结请求与历史失败。

# Choice execution decisions / Choice 执行判断

当前源码将点击、全选和替换合为一个动作，删除中间字段Decision；输入后只检查规定文字，不增加点击后的焦点外观或吞点击确认。输入候选 Choice 当前限定直接遮挡和明确交互前置条件，不预测吞点击，相关离线检查及有 Main 介入的源码恢复路径实测已通过，安装、独立及发布验收未完成，见[发布记录](../verification/EXECUTION_STABLE_012_20261012.md)。 / Current source combines click, select-all and replacement, with no intervening field Decision and a text-only post-input check. Input-candidate Choice now limits popup review to direct obstruction and explicit prerequisites, without predicting click consumption. Related offline checks and source recovery with Main intervention passed; installed/independent acceptance and publication remain open.

新候选随后由 Main 实测：第一轮 Google→java→首个普通结果 3/3 完成，第二轮在 Google 候选动作前准确拒绝翻译弹层（`condition_not_met`、`action_executed=false`，无 Ctrl+A/V/Enter），宿主清理成功。后续正式恢复验收在同一会话中，两轮均先零输入阻断，再经 `recover` 关闭翻译弹层、`resume_pre_dispatch` 续原 run，各 3/3 完成且各需一次 Main 介入；正常收尾并保留资料目录。恢复路径通过，**不是无人干预两轮通过**；旧 Enter 跳转故障的完整根因及安装、独立、发布验收仍未闭合。 / Main first observed one complete 3-step round followed by a pre-dispatch popup refusal with no input and verified host cleanup. In the subsequent formal recovery session, both rounds initially stopped without input, then completed all 3 steps on the original runs after `recover` dismissed the popup and `resume_pre_dispatch` continued, with one Main intervention per round. Normal closure retained the profile. Recovery passed; **this was not unattended two-round success**. The complete cause of the earlier Enter/navigation failure, installed/independent acceptance and publication remain open.


Execution 0.1.2 uses OpenAI Decisions API with `gpt-6-luna`. Artifact status and live evidence: [release record](../verification/EXECUTION_STABLE_012_20261012.md). / 执行 0.1.2 接入 Choice；安装与实测状态以发布记录为准。

## Contract / 合同

- One question per checkpoint: `type: choice`, `name: current_step`, with `condition_met`, `condition_not_met`, `evidence_insufficient`. / 每个审核点一次三选一，不代表整个任务一次请求。
- In auto mode, met adopts/continues; unmet is failure and insufficient is uncertain, both requiring the existing Main. Provider refusal, invalid responses and timeouts also return for review without automatic input replay. / 满足继续，不满足或证据不足交原 Main；服务异常不重放输入。
- Raw `choice_result` retains choice/confidence/probabilities. Legacy predicate projections remain empty, and no fabricated binary probability or second threshold veto is introduced. / 保留原始选择分布，不伪造概率或叠加旧阈值。
- Eligibility, explicit always_main/shadow modes, action permissions, window/coordinate/image bindings, cancellation and deadlines remain effective. / 条件许可、权限、绑定及停止规则仍有效。

## Current visual evidence / 当前视觉证据

候选 Choice 的生产 provider 已改为同一次请求的一张概览＋细节 PNG：overview 最长边640px，完整候选框及附近上下文的 detail 最长边768px，小目标最多2倍；空心标记保留中心±6px。模型仅接收当前目标、动作kind、必要映射及当前allowed states/popup事实；原SHA、窗口身份、几何与账本认证仍留本地，旧v1标注和无标注回执兼容。阈值、wait、重试及输入后仅比文字的合同不变。 / The production candidate Choice provider now sends one overview/detail PNG in the existing request: a 640px maximum-edge overview and a complete-box detail with nearby context, a 768px maximum edge and up to 2× scaling for small targets. Hollow marks preserve ±6px around the center. Only the current target, action kind, necessary mapping and current allowed states/popup facts reach the model; full hashes, identity, geometry and ledger authentication remain local, including legacy v1 marked/unmarked receipts. Thresholds, wait/retry policy and text-only post-input checks are unchanged.

新视图仅用于单帧before-action、`CANDIDATE_CONDITION`、candidate scope、Choice、有有效`permitted_action.kind`且无freshness的路线；其他predicate/custom/freshness/multi-frame/unmarked/缺省permitted action保留原wire。输入动作逐字保留原交互弹层可行性说明，不增加截图、API请求、点击后焦点/空框检查或未来结果要求。 / The new view applies only to single-frame before-action Choice candidate review under `CANDIDATE_CONDITION`, with valid `permitted_action.kind` and no freshness context. Other predicate/custom/freshness/multi-frame/unmarked/omitted-permitted-action routes retain their previous wire. Input actions retain the original popup-feasibility clarification verbatim; no capture, API request, post-click focus/empty check or future-result requirement is added.

Field checks still use the complete field and recorded click; ordinary click outcomes use the full current image, without cropping by the old candidate box. / 字段仍用完整字段和真实点，普通点击结果使用当前整图，不按旧候选框裁剪。

Choice receives only useful visual coordinates and crop mapping from annotation metadata. Full source/receipt hashes, window identity and coordinate authentication remain local and are revalidated before sending and adopting results. A marker is a historical click, not a current target or proof of success. Existing stored results retain their original authenticated binding without a new request. / Choice 仅接收标注中有助于读图的坐标与裁剪映射；完整哈希、窗口身份和坐标绑定仍在本地发送前及采用前重验。标记只代表历史点击，不证明当前目标或任务成功；旧结果按原绑定认证，不补发请求。

Ordinary static outcome Choice asks only whether the current declared result is visible, without rechecking action feasibility or earlier/future work. Required evidence outside the capture, clipped by a crop, or hidden persistence remains insufficient. No thresholds, retries, UIA scan or extra model call were added. This does not turn a visible text/menu check into proof that a document was saved. / 普通静态结果只判断当前声明结果，不复审动作可行性或前后步骤。未采集、被裁掉或隐藏的持久化证据仍属不足。本次不改阈值，不增加重试、UIA或模型调用；文字正确且菜单关闭不能冒充保存成功证明。

The historical split-step field question was: “Is the center of the cyan recorded-click marker inside the intended text input described by action.field.field_goal?” It described that earlier version, without caret, keyboard-focus, empty-field or future-navigation checks. The current compound path has no separate post-click field checkpoint. / 历史分步版本仅判断实际点击点是否位于目标输入框内，不检查光标、焦点、空框或后续跳转；该描述限于旧版本，当前组合路径没有独立的点击后字段审核。

## Changed appearance before action / 动作前外观变化

When the selected target region changes while grounding runs, an eligible auto Choice action review can assess the original point on the current marked image through its existing request. The old 2% pixel rule no longer vetoes that path before Decision. This is pending review, not permission to dispatch: the current scope, frame, original candidate, window identity, profile, deadline and authenticated passing assessment must still match immediately before input. Unmet or insufficient outcomes dispatch nothing. Without eligible Choice, the prior pixel check remains. / 定位期间目标区域外观变化时，可用的 auto Choice 通过原有请求审核当前标注图上的原点击点，不再先被旧2%像素规则否决。此时只是待审核，不能派发；实际输入前仍核对同一审核作用域、当前图、原候选、窗口身份、配置、时限和已认证的通过结果。不满足或证据不足均零输入；没有可用 Choice 时保留原像素检查。

This adds no screenshot, model call, wait or retry. Source contract checks passed; new real-flow acceptance remains pending. / 不增加截图、模型调用、等待或重试。源码合同检查已通过，新的真实完整流程仍待验收。

## Current candidate and field scope / 当前候选与字段范围

Candidate Choice checks the marked target meaning, direct obstruction, disabled state and explicit interactive prerequisites. An unrelated popup that does not block the target is not itself a blocker. It no longer predicts whether a click would merely dismiss a popup; no post-click focus/consumption check was added. / 候选仅判断目标语义、直接遮挡、禁用状态与明确交互前置条件；无关且不阻挡目标的弹窗不单独拒绝，不再预测点击是否只关闭弹窗，也不恢复点击后焦点或吞点击确认。

For authenticated single-field text-only Choice, the complete original ROI is enlarged 2× (RGBA/LANCZOS), with historical-click coordinate ticks in an added 8px upload margin so no glyph is covered. The displayed image contains no generated expected text. One image and one question carry the exact comparison literal; bookkeeping stays local. An attached gray unaccepted continuation asks for Main review in the same Choice; separate shortcut hints are ignored. Full original/hash/receipt and expected value remain bound. The padded view must fit 4096px and 4,000,000 pixels; larger fields keep the legacy image and request. Predicate, unmarked and other checks are unchanged. / 已认证单字段文字Choice对完整原ROI放大2倍，再在上传图外侧8px边距画历史点击坐标刻度，字段内部不盖字、不生成期望文字。仍只发一图、一个含规定文字的比较问题；紧贴输入的灰色未接受补全交Main，忽略独立快捷提示。原图、哈希、回执及期望值完整绑定；带边距超过4096最长边或400万像素时保留旧图旧请求，兼容路线不变。

Default replacement selects all and types the requested value; no empty-field OCR/classification or post-selection model check runs. The value question checks only the expected text. Candidate and outer task-outcome checks are additional checkpoints. See [visual input](VISUAL_EXECUTION_INPUT.md). / 默认全选替换，不判断空框、不审核全选；输入后仅核对规定文字。候选审核和外层结果核验另计。

## Candidate usage checks / 候选用法检查

正式payload的4个保留图正反例均符合预设判断：SELECT满足、合成错点UPDATE不满足、翻译弹层阻挡不满足、无弹层输入可行满足。Input tokens约少53–57%；0桌面动作、无动作授权、未采用结果、无自动重试。小样本不证明通用准确率、速度或部署通过。 / Four retained-image production-payload cases matched preset labels: SELECT met, synthetic UPDATE wrong point unmet, popup-blocked input unmet and unobstructed input met. Input tokens fell about 53–57%. There were no desktop actions, action authority, result adoption or automatic retries. This small sample establishes no general accuracy, speed or deployment acceptance.

HTTP时间不包含本地准备。4例各5次无API测量的render中位26.76–31.88ms，组包至mock HTTP中位29.53–34.09ms（含render）；wire摘要与正式请求相同。 / HTTP times exclude local preparation. Five local, API-free measurements per case gave median rendering of 26.76–31.88ms and packaging through mock HTTP of 29.53–34.09ms including rendering, with identical production wire digests.

离线：Main 133 passed in 1.81s（`candidate-view-main.xml`）、集成93 passed in 12.69s（`candidate-view-integration-main.xml`），worker25 passed in 0.94s（`candidate-view-provider-green.xml`）；重叠不相加。 / Offline: Main passed 133 in 1.81s, integration 93 in 12.69s and the worker 25 in 0.94s; these overlapping groups are not summed.

The failed SQLite first attempt is unchanged. MDN stopped at a visible translation popup before a correctly located link; the cause is not classified as false rejection. Build03 and installed acceptance remain pending; see the [release record](../verification/EXECUTION_STABLE_012_20261012.md). / SQLite首败保留，MDN在可见翻译弹层处拒绝正确点位，尚不认定误拒；build03及安装验收待完成，详见发布记录。

## Configuration and compatibility / 配置与兼容

The base, adaptive and visual-execution example profiles explicitly select Choice. New hosts load/freeze them through `--decision-profile`; running hosts are not hot-updated. Omitted or explicit predicate format preserves historical probability routing and receipt serialization. Thresholds apply to predicate, not Choice. / 新示例显式选择 Choice，新宿主加载冻结；旧 predicate 配置与回执按原义保留。

Default visual input requires an eligible auto-mode Decision service. Without it, choose basic actions, compatible v1/v2 plans or explicit `field_evidence_mode="legacy"`; no implicit fallback is performed. / 默认视觉组合输入需要可用的 Decision auto；无 API 仍可显式使用原生/基础路线，不自动降级。

## Partial input and evidence / 部分输入与证据

Rejected click/value checkpoints retain the original request, authenticated judgment and real dispatch prefix. Known failures settle as failed; genuinely unknown dispatch remains unknown. The existing Main receives a read-only handoff and must explicitly review or replan; the handoff is not permission to replay. / 保留真实已执行前缀，已知失败不记成未知，真正未知不虚构零输入；交接不授权重放。

Historical failures remain in [Choice acceptance](../verification/DECISION_CHOICE_RUNTIME_20261012.md) and later verification records. The current source's successful rerun is recorded in [overlay acceptance](../verification/RECORDING_OVERLAY_ALLOWLIST_20261012.md). A small sample is not a general accuracy claim. / 首败和后续复测分别记录，不宣称通用准确率。
