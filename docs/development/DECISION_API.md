# Optional Decision API / 可选判断 API

## 当前入口 / Current entry

已发布执行版为 **0.1.3**，见[执行指南](../EXECUTION_GUIDE.zh-CN.md)。本轮源码更新保持版本号不变，新增 Decision／普通复核独立接口、模型和密钥变量配置；默认方案不变，示例、协议边界与恢复行为见[中文配置](DECISION_PROVIDERS.zh-CN.md)和 [English configuration](DECISION_PROVIDERS.md)。 / The published execution release is **0.1.3**; see the [execution guide](../EXECUTION_GUIDE.md). This source update keeps the version unchanged and independently configures the two endpoints, models and credential variables while preserving defaults. The linked configuration guides define compatibility and recovery behavior.

下方内容为开发历史，包括当时尚未完成的验收状态，不代表当前发布状态。 / The sections below are historical checkpoints, including acceptance that was pending at the time; they do not describe current release status.

## 历史开发记录 / Historical development records

当前执行 0.1.2 以 [Choice 合同](DECISION_CHOICE.md)、[视觉输入](VISUAL_EXECUTION_INPUT.md)及[首页配置](../../README.md)为准。下方日期章节保留演进与兼容语义，其中历史空框分类、全选审核、整图上传等描述不再代表默认视觉路径。 / For current execution follow the linked contracts and setup. Dated sections below retain historical checkpoints; superseded empty-field, selection-review and full-frame descriptions are not the current defaults.

**执行 0.1.2 连续输入已实现，有 Main 介入的源码恢复路径实测通过，安装/独立/发布验收未完成 / Execution 0.1.2 continuous input is implemented and source recovery passed with Main intervention; installed/independent acceptance and publication remain open.** 普通视觉输入改为定位审核通过后，同一次动作连续点击、Ctrl+A、替换文字，随后只核对规定文字；点击和输入之间不插入Decision、截图或重新激活，不增加点击后的焦点外观、空框或吞点击确认。原门禁、目标绑定、取消、截止和真实阶段回执保留；失败不自动重放。源码与连续实测完成状态见[本次记录](../verification/EXECUTION_STABLE_012_20261012.md)及[视觉输入说明](VISUAL_EXECUTION_INPUT.md)。 / The default revision performs click, select-all and replacement continuously after target approval, then checks only the requested value. No intervening Decision, capture or activation is added. Existing gate/binding/stop checks and genuine dispatch receipts remain; failures do not authorize replay. Source and live acceptance are tracked separately.



新候选随后由 Main 实测：第一轮 Google→java→首个普通结果 3/3 完成，第二轮在 Google 候选动作前准确拒绝翻译弹层（`condition_not_met`、`action_executed=false`，无 Ctrl+A/V/Enter），宿主清理成功。后续正式恢复验收在同一会话中，两轮均先零输入阻断，再经 `recover` 关闭翻译弹层、`resume_pre_dispatch` 续原 run，各 3/3 完成且各需一次 Main 介入；正常收尾并保留资料目录。恢复路径通过，**不是无人干预两轮通过**；旧 Enter 跳转故障的完整根因及安装、独立、发布验收仍未闭合。 / Main first observed one complete 3-step round followed by a pre-dispatch popup refusal with no input and verified host cleanup. In the subsequent formal recovery session, both rounds initially stopped without input, then completed all 3 steps on the original runs after `recover` dismissed the popup and `resume_pre_dispatch` continued, with one Main intervention per round. Normal closure retained the profile. Recovery passed; **this was not unattended two-round success**. The complete cause of the earlier Enter/navigation failure, installed/independent acceptance and publication remain open.

## 2026-10-12 输入候选可行性补充 / Input-candidate feasibility clarification

仅在 provider 的候选 Choice 且原动作属于 `input_sequence` 时，在既有点位问题中补充以下说明；普通 click 和 predicate 路线不添加该说明。 / Only candidate Choice for an original `input_sequence` appends the following clarification to the existing point question; ordinary clicks and predicate requests do not add it.

> This click starts text input. Can it directly reach the target without first handling an interactive popup? If a visible interactive popup must be handled first, or this click would only dismiss it, the current action cannot proceed.

本次点击将开始文字输入：能否不先处理交互弹窗就直接到达目标？若可见交互弹窗必须先处理，或本次点击只会关闭它，则当前动作不能继续。

仍使用同一次请求、同一张候选标注图，原条件与阈值不变。这是派发前对当前动作能否直接开始输入的判断，不增加点击后的焦点外观或“点击被吞掉”确认；点击、全选、替换之间仍无 Decision、截图或重新激活，输入后仍只比规定文字。 / The same request and marked candidate image are used, with unchanged original condition and thresholds. This is a pre-dispatch feasibility question, without a post-click focus-style or click-consumption check. Click, select-all and replacement remain uninterrupted by Decision, capture or activation; the post-input check remains text-only.

原图对照、生产请求体一致性及 Main 的 9 模块 186 项离线结果见[本次记录](../verification/EXECUTION_STABLE_012_20261012.md)。有翻译弹层样本 baseline 放行、补充版拒绝；无弹层样本两者均放行，仅两样本不能泛化。200ms Enter 对照已回退，回退检查 35 项通过，不保留额外输入间隔。 / See the release record for the retained-frame comparison, production wire parity and Main's 186 checks across 9 modules. Baseline/proposed differed only on the popup sample; both passed the no-popup sample. Two samples cannot generalize. The 200 ms Enter experiment was reverted with 35 checks passing; no added interval remains.

下方早期内容分类/可输入审核条目仅为历史检查点，已被默认全选替换取代。 / Earlier content-classification/readiness checkpoints below are historical and superseded.

历史记录（已被默认替换取代） / Historical, superseded by default replacement. 2026-10-12 本地OCR与字段裁剪：新视觉Choice的 `after_click` 仅用Decision判断目标能否输入，不再发送 `field_content` 问题。本地RapidOCR读取未标注完整字段及16px周边裁剪，字段审核每帧只上传一张实际点击标注裁剪图，原图/source SHA/窗口与坐标留在本地。Main最终22模块536项离线回归通过；同一保留误拒图单次正式API返回 `condition_met`，随后一轮完整浏览器复测3/3自动通过、无Main接管；不能据此证明连续稳定性、裁剪单一因果或提速。旧两轮未通过记录保留。详见[OCR裁剪记录](../verification/OCR_FIELD_CROP_20261012.md)。 / New visual Choice after-click review checks usability only; local RapidOCR handles content from the unmarked field crop. Each field frame uploads one marked crop with full provenance retained locally. Main's 536 final offline checks and one retained-frame API replay passed; a subsequent full browser run passed 3/3 without Main intervention. Continuous stability, crop-only causality and speed gains remain unproven.


## 2026-10-12 Choice 直接选择 / Direct Choice

新 v2 示例显式设置 `decision_format: "choice"`。每个现有检查点只发送一个 `current_step` 三选一问题；`condition_met` 继续，`condition_not_met` / `evidence_insufficient` 回原 Main，不再对 confidence 或选项概率设通过阈值。拒答、协议错误、超时和证据认证错误也停止交接，绝不转换成通过。旧数值阈值未改，仅 predicate 路线继续使用；省略字段保留旧 profile 摘要兼容性。 / New v2 examples explicitly select Choice: one current-step classification; met continues and unmet/insufficient returns to Main. Confidence is diagnostic only. Refusals, errors and timeouts cannot approve input. Unchanged thresholds apply to predicate profiles; omission preserves legacy digests.

详见 [Choice 合同](DECISION_CHOICE.md) 和 [本批验证](../verification/DECISION_CHOICE_RUNTIME_20261012.md)。下文阈值与 needs_agent_review 说明保留为 predicate 路线及历史批次。 / See the contract and batch evidence. Threshold and needs_agent_review sections below describe predicate compatibility and historical checkpoints.

## 2026-10-12 历史 OCR 视觉输入检查点 / Historical OCR visual-input checkpoint

本轮OCR/裁剪源码接入和最终相关离线回归已完成，随后一轮完整浏览器复测3/3自动通过；连续稳定性仍待验证。新普通提交用截图与Decision审核目标可用性和输入后文字，本地RapidOCR只提供保守的字段内容分类；UIA仅保留学习或显式原生路线。阈值、窗口/坐标绑定、原始回执、取消和截止时间仍有效，旧冻结计划及回执不重新解释。见[视觉输入闭环](VISUAL_EXECUTION_INPUT.md)。 / Source integration and final related offline checks are complete; a subsequent full browser rerun passed 3/3 automatically, with continuous stability still unproven. New ordinary input uses Decision for usability/text checks and local OCR for conservative content classification. UIA remains explicit/learned; thresholds, bindings, receipts and stop gates are preserved without reinterpreting frozen evidence.

## 2026-10-12 当前结果范围 / Current-result scope

`after_action` 的远端输入只包含当前声明条件、当前截图与允许的当前动作证据；不上传完整 `review_context`、全局目标或剩余计划，嵌套历史字段也被剔除。`needs_agent_review` 只判断妨碍确认当前结果的歧义、遮挡、异常或错误，不要求前序流程重新证明或后续步骤提前完成。显式原生路线提供的真实字段值、焦点和绑定事实仍保留。 / After-action wire content contains the current condition, frames and permitted current action facts, excluding full workflow context and nested history. Review asks only about issues establishing this result, retaining genuine field/focus/value evidence from explicit native routes.

完整原请求和计划上下文仍用于本地认证、摘要和账本；`before_action` 仍按原任务与动作上下文审核。专用原生字段和动态内容问题、采用阈值及原动作门禁不变。旧宿主不热更新，需新连接加载源码。 / Full original context remains authenticated locally. Pre-action review, dedicated native/temporal predicates, thresholds and input gates are unchanged. Existing hosts require a new connection to load the change.

前序检查点：485 项离线通过；独立浏览器首轮三步自动完成，同会话复跑停在原生字段几何读取、未进入 after-action。profile 已保留，不能宣称连续稳定或性能收益；见[完整证据](../verification/DECISION_CURRENT_STEP_SCOPE_20261012.md)。下方实测状态为各自历史批次。 / Earlier checkpoint: 485 offline checks and one full automatic run passed; the repeat failed before after-action at a native field-geometry read. The isolated profile is retained; continuity and performance benefits remain unproven. Validation statements below describe earlier slices.

## 2026-10-12 历史点击点审核 / Historical point-only candidate review

历史点位版本（2026-10-12）：候选 Decision 的问题改为“点击标记的中心是否落在指定可见目标内部”；派生图只画青色点击环/十字，不画矩形框。原图仍同请求上传。候选bbox仅保留于原绑定及坐标校验；0.80阈值、安全及接管规则不变。354项离线检查通过（6.64s），已用上轮截图验证点图，未新增API或桌面实测。此前.64失败属于框图版本，原始证据保留。 / The earlier candidate Decision asked whether the click-marker center lay inside the specified visible target. The derived image shows only the cyan point marker; the original remains in the same request. Bounding-box metadata is retained for binding and coordinate validation. Threshold0.80, safety and review rules are unchanged.354 offline checks passed in6.64s; the point preview uses the prior capture, with no new API/desktop test. The earlier.64 failure belongs to the box-rendering version.

问题 / Predicate: `Does the center of the cyan click marker fall inside the visible UI target described below? Use the original image if the marker obscures a detail.` 后附当前目标描述 / Followed by the current target description.

## 2026-10-11 未发布：统一动作审核 / Unreleased unified action review

新 `task_plan.v3` 将完整任务、当前和剩余步骤、候选、窗口/截图、profile 与 attempt 绑定在同一审核中。默认顺序为 **Luna 定位 → 一次候选 Decision → 原输入门禁 → 动作 → 原结果核验**。候选 Decision 同时判断目标可用性、弹窗影响和语义安全；DOM 遮罩也进入此审核。原生窗口检测保留为身份、位置、真实命中等事实，不再仅凭存在弹窗拒绝。 / V3 binds the full task, remaining steps, candidate, window/frame, profile and attempt. One post-grounding Decision assesses feasibility, obstruction and semantic safety before the existing gated action and outcome checks. Native checks contribute facts rather than blanket popup refusal.

使用[新配置示例](../../configs/decision-profile.visual-execution.example.json)，其中明确批准代码定义的候选、新鲜度、视觉字段及可选场景条件；不要手写近似条件代替精确字符串。现有冻结配置、阈值和额度不热改，`scene_precheck` 默认 `off`。旧 v1/v2 和无 Decision 的兼容路线保留；缺少服务、额度、条件许可或配置为 always_main 时会说明原因，不冒充模型判断，也不自动切换供应商。 / Use exact predicates from the new example. Existing frozen configuration, thresholds and caps are unchanged; optional scene precheck defaults off. Unavailable service, exhausted budget, missing permission or always-main is reported explicitly, not as a model verdict or provider fallback.

以下为已被连续替换方案取代的历史OCR路线，不描述当前默认行为；当前逻辑见[视觉输入说明](VISUAL_EXECUTION_INPUT.md)。 / The following OCR route is superseded; see the current visual input design. 普通点击仍按候选及可选结果审核计数。历史视觉组合输入另有一次点击后可输入Decision、可选替换选区Decision及输入后文字Decision；不再增加 `field_content` 问题或为OCR增加HTTP。OCR检出文字记nonempty（可能是占位/按钮）；无检测仅在剔2px边框后的完整字段内侧每像素同色且非透明时证明empty，其余uncertain。严格空框跳过Ctrl+A/选区；nonempty或uncertain且原 `clear_existing=true` 走既有授权替换，仍受selection/value检查；False未证明空则不输入。新 `visual_typing_strategy.v2` 认证OCR策略；旧field_content v1只读认证兼容。值请求仍为 `value_verification:"visual"`、`actual_text/value_reading:null`，只比较规定文字，不检查焦点。原额度、取消、截止与不重放合同保持。 / Calls remain candidate/optional outcome plus input usability, optional replacement and text-only value. OCR adds no HTTP or field-content question. Detected text is conservatively nonempty; only a wholly uniform opaque complete interior after a 2px border proves empty. Authorized replacement handles nonempty/uncertain; no-clear requires empty proof. Strategy v2 binds OCR while v1 remains historical. Existing caps, stop gates and no-replay rules remain.

Decision 结果只提供认证证据，始终 `authorizes_action=False`。原线程仍核对原动作、窗口、坐标、取消状态和实际输入回执；零输入恢复产生新 attempt，部分或未知输入不重放。源码已做离线验证；获准的真实尝试在首次输入前暂停，随后同图只读 API 对照并不代表完整任务通过，详见[证据与限制](../verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md)。 / Authenticated results do not independently grant input authority. Original-thread gates remain. Proven zero-input recovery creates a new attempt; partial/unknown input is never replayed. The approved live attempt stopped before input; later read-only API comparisons do not establish full-flow acceptance.

## 通用三图目标判断 / Generic three-frame target assessment

`temporal_visual_change.v1` 使用视频v2的闭合字段并添加 `target_description`；该描述进入请求摘要、metadata和采用校验。上传全部三张原PNG，一次判断指定内容本身是否变化，忽略外围动画、鼠标、遮挡与加载装饰；无法判断则交原Main。普通静态协议和视频v1/v2语义不变。 / The generic schema adds an authenticated target description to the strict v2 fields. All three original PNGs are assessed once; unknown target change returns to Main without reinterpreting existing protocols.

对应 `task_plan.v2/verification.kind=dynamic_content`，详情见[用法](TASK_PLAN.md)和[真实证据与限制](../verification/THREE_FRAME_DYNAMIC_CONTENT_20261011.md)。安装器未更新。 / This is unreleased source, with scoped live evidence rather than a general accuracy claim.

## 分阶段独立阈值 / Independent phase thresholds

2026-10-12 用户同意放宽动作前通过概率。新源码样例显式配置 `before_action_pass_threshold: 0.80`，仅改变 `before_action` 的条件满足门槛；危险分数须 <=0.10、动作前接管分数 >0.10 转 Main 的规则保持。该字段仅支持 v2，省略或 null 沿用旧 `pass_threshold`，不改变旧摘要。此前同图正例0.86在旧0.90配置下仍记为未采用；新阈值已通过257项相关离线测试，尚未重新进行桌面/API验收。 / On 2026-10-12 the user approved a lower pre-action feasibility threshold. New examples explicitly set `before_action_pass_threshold: 0.80`; danger and pre-action review boundaries remain unchanged. The optional v2 field preserves old serialized profiles when omitted or null. The historical 0.86 sample remains unadopted under its frozen 0.90 profile; 257 relevant offline checks pass, with no new live/API acceptance.

用户已选择新源码配置 `after_action_pass_threshold: 0.80`、`after_action_review_threshold: 0.70`。前者只用于动作后的条件满足分数；后者表示needs_agent_review达到0.70才因这项转Main。可见错误仍须<=0.10才可成功，>=0.90仍按明确错误处理；still_progressing沿用原阈值；动作前可行性使用上方独立字段。 / These after-action fields separate outcome confidence from Main routing without changing error or loading thresholds; pre-action feasibility uses the independent field above.

这些v2字段未提供时保持旧规则和旧序列化摘要；v1不接受它们。新示例及下一轮实测配置显式写入，旧宿主和旧证据不热更新。`pass_threshold:0.9`仍保留为旧规则、错误/危险和加载的高阈值；动作前只有未配置独立字段时才继承它，不能直接改成0.8代替上述字段。只有符合原允许条件和有效原票据才能自动采用；always_main仍交Main。 / Omitted fields preserve frozen legacy semantics and hashes. Explicit examples apply on a new session; old receipts cannot be reinterpreted or redispatched under a changed profile.


**未发布三图核验 / Unreleased three-frame verification:** 显式 `video_playback` 新路径使用闭合的 `temporal_playback.v2`，仅含 `{schema,original_after,samples,selected_capture_ids,timeout_seconds}`；`samples` 严格三项 `{frame,elapsed_ms}`，不接受调用方追加region、analysis或state/position。输入完成及render_grace结束后首图至少1000ms，相邻至少500ms、跨度至少1000ms、每帧均小于8000ms；采样与本次唯一判断/采用共用原8秒预算，timeout_seconds取剩余预算。 / The explicit playback route uses a closed v2 context with exactly three frame/time samples. Capture timing starts after input and render grace; sampling, one assessment and adoption share the existing8s budget.

原 after 独立绑定且不上传。三张不同capture ID/路径的真实静态PNG须通过session路径、SHA、同窗口/尺寸与实际时间顺序认证，selected_capture_ids严格等于全部样本顺序；实际全部上传为 `sample_start/sample_middle/sample_end`。专用问题只问目标视频内容画面在三图间是否变化，有变化按播放；排除无关页面与按钮显隐，不额外要求控件或进度佐证。新路径无额外Luna定位、OCR或本地播放成功依赖。 / Authenticate the separate original after without uploading it, and upload all three distinct, ordered static PNGs with start/middle/end roles. The dedicated question checks target-video picture change, excluding unrelated page/control changes, without control/progress corroboration or extra grounding/OCR/local-success requirements.

自动采用仍须原票据、获准确切条件、错误及审核门禁；上方0.80/0.70仅由新profile显式字段选择，普通静态问题、1–2张限制及省略字段的旧规则不变。无API或always_main仍采三图交原Main；拒绝、不确定、超时/晚返不重复判断或重放输入。`temporal_playback.v1` 仅保留历史兼容。 / Original-ticket authentication, exact condition approval and other gates remain. Explicit new-profile fields select the thresholds above without widening static protocols or reinterpreting omitted legacy fields. No-API/always-main collects three frames for Main; refused, uncertain or late results never replay input or loop assessments.

视频v1仅历史兼容；旧7.797s/6.990s属于旧实现，当前限定正负例与剩余验收范围见上方最新记录。 / Historical timings do not validate the new path; current scoped results and limitations are linked above.

Published preview.3 includes [temporary task plans](TASK_PLAN.md) with explicitly declared outcome checks. The adaptive review and bounded-observation protocol below remains unreleased. Its earlier frozen source passed [862 offline cases with one permission-related skip](../verification/ADAPTIVE_REVIEW_OFFLINE_20261009.md); subsequent repairs have separate evidence in the [live acceptance record](../verification/ADAPTIVE_REVIEW_LIVE_20261009.md). That earlier result does not validate every later source change or a new installer. / preview.3 已包含临时计划；下方主动审核及有限观察尚未发布。862项通过、1项权限跳过属于此前冻结源码，后续修复另有记录，不能把旧结果转计当前全部源码或新安装器。

## Adaptive review v2 (unreleased) / 主动审核 v2（未发布）

普通视觉执行使用上方链接的 `decision-profile.visual-execution.example.json` 和 `task_plan.v3`；本节通用/adaptive 示例仅用于兼容说明，其白名单并不包含完整视觉输入条件。 / Ordinary visual execution uses the linked visual-execution profile and task_plan.v3. The general/adaptive examples in this historical section do not include the complete visual-input allowlist.

New source configurations use the [main profile example](../../configs/decision-profile.example.json) or the identical [adaptive profile example](../../configs/decision-profile.adaptive.example.json): `contract_version: decision_profile.v2`, `mode: auto`, `proactive_review: true`, `review_policy: adaptive`. An explicit v2 file with omitted mode also resolves to auto. Exact string `auto_conditions` or typed-template identities still require explicit approval; the default empty allowlist does not approve conditions or pending learning drafts. / 当前源码新配置的主样例与 adaptive 样例一致，默认 v2/auto、主动审核开启、策略 adaptive；明确 v2 文件省略 mode 也解析为 auto。完整字符串条件或模板身份仍须明确批准，默认空允许列表不批准任何条件或 pending 学习草稿。

Explicit shadow/off/always_main settings, v1 profiles and frozen sessions retain their semantics; v1 with omitted mode remains shadow. The low-level DecisionProfile constructor without a version remains v1-compatible, while profile files still require an explicit contract_version. Published preview.3 uses the [legacy v1 profile](../../configs/decision-profile.legacy.example.json). These defaults are unreleased source changes, not a package update or hot reload. / 显式 shadow/off/always_main、旧 v1 配置及冻结会话保持原语义；v1 省略 mode 仍为 shadow。底层 DecisionProfile 无版本构造保留 v1 兼容，配置文件仍须明确 contract_version。已发布 preview.3 使用 legacy v1 配置；当前默认调整未打包、未发布，不热更新宿主。

Adaptive review is the default orchestration; the Decision API is optional. No configured profile means Decision is inactive, even when the named key exists in the environment. Complete local proof continues without API; otherwise the original wait returns to the existing Main. New caller plans explicitly use task_plan.v2; omit per-step review_policy to inherit the host, or set only always_main to tighten it. / 主动审核编排默认采用，Decision API 可选。未配置 profile 不启用 Decision，不因环境中有 key 自动连接；完整本地证明零 API 继续，否则沿原 wait 交回已有 Main。新临时计划显式使用 task_plan.v2；单步省略 review_policy 沿用宿主，或仅设 always_main 收紧审核。

`proactive_review: true` adds a third independent predicate, `needs_agent_review`, to the same request. `review_policy: adaptive` may continue only after authenticated success without an intervention signal. `always_main` requests Main review without paying for a preliminary judgment. A per-step always_main policy can tighten the profile, never weaken it. / 主动审核在同一次请求中增加独立问题；adaptive 仅在成功且无需接管时继续。always_main 直接交主 Agent，不先付费；步骤只可收紧宿主策略。

The outcome `verdict` and runtime `disposition` are separate. Success with `review_required` preserves the original input facts but does not verify the task effect or release the next action. Requested-but-missing answers and conflicting results cannot be adopted. Disabled questions are explicitly not requested; they are never synthesized as probability zero. / 结果与路由分开：成功也可待审核；已请求缺答和冲突不自动通过，关闭的问题不伪造概率零。

V2 freezes a bounded `review_context` containing the task, current step, remaining-plan summary and allowed states in the authenticated request. An explicitly standalone check supplies an empty remaining plan; a missing context with proactive review enabled returns to Main without a paid request. V2's request cap covers the whole host session, including learning runs; creating another run does not reset it. Status exposes used/remaining and unresolved dispatches without creating storage or calling the provider. / v2 将有限上下文纳入认证；单步明确提供空后续计划，开启主动审核却缺上下文时不付费并交 Main。v2 额度覆盖宿主内执行及学习运行，新运行不重置；状态只读展示用量。

V2 caller plans keep the string-shaped `step_goal` and `remaining_plan` contract, but each string is a deterministic compact JSON step summary containing the step ID, action kind/goal, input parameter reference (or explicit literal/constant redaction), input flags/click kind and declared verification condition. No resolved input values or arbitrary target metadata are copied. Empty `allowed_states` means no extra state list was declared, not that every visible state is forbidden or that any new action is authorized. / v2临时计划保留字符串字段，内容为确定性紧凑JSON步骤摘要；包含步骤ID、动作、参数引用或隐藏标记、flags和声明验证条件，不复制解析后输入值及任意目标元数据。空allowed_states表示未声明额外状态，不能解释为全部禁止或新增动作授权。

After all step structures validate, v2 admission preflights each context with the same normalizer used by the provider: current summary≤4000 characters, each remaining summary≤2000, total≤64KiB including the real74-character source ID. Oversize is rejected before any command is queued; no silent truncation. Long goal/condition combinations accepted by older development source may need shortening. V1 remains unchanged. V2 summaries enter authenticated bindings/hashes: finish or cancel active runs on their original frozen runtime and start a new run after upgrading; do not recompute old evidence with this projection. / 全部步骤结构验证后，v2入队前以请求同一normalizer检查当前4000字、后续单项2000字及整体64KiB（包含74字符source_id）；超长明确拒绝、不静默截断。部分旧开发源码接受的长组合需缩短；v1不变。v2摘要参与认证与哈希，升级前用原冻结运行时终结或取消活动运行，升级后新开运行，不用新投影重算旧证据。

`instant_status` now validates the frozen session profile and reads current budget counts from the original ledger instead of displaying only the host-start snapshot. Polling does not create a service, send a request or change authenticated assessment budgets. Only a new session with no persistence directory reports zero; a missing/invalid ledger under existing persistence, changed profile or failed read returns `budget_status=unavailable` with null counts. V1 retains its execution-only status scope. / 当前源码的状态查询核对冻结配置并只读原账本，修正启动快照一直显示零用量的问题；查询不新建服务、不请求 API、不改认证结果的入场预算。只有尚无持久目录的新会话显示零，已有目录却缺账本、坏账本、配置变化或读取失败均返回不可用及空计数；v1 维持执行范围。

For v2 explicit before-action checks in auto mode, an unallowlisted condition returns to Main without a paid call or input; it does not silently bypass the requested check. Post-action advice still preserves whether the original input occurred. V1 keeps its historical behavior. / v2 auto 动作前显式检查若条件不在允许范围，则不付费、不输入并交 Main；不能把跳过检查当通过。动作后保留原输入事实；v1 不变。

The source includes proactive handoff, the condition/policy editor, automatic declared-loading observation and explicit v2 native-timeout continuation. The optional fourth predicate, `still_progressing`, is requested only for explicit `wait_policy`; observe stays uncertain, and missing answers/errors/review signals override waiting. Manual read-only observe is now implemented through the same retained wait without another API assessment. Typed-template shared profile/service, caller-plan binding and the editor are now implemented in source; learning-core integration is also implemented and included in Main's frozen offline regression. No new observation is represented as the original after frame, and end-to-end benefits remain unproven. See the [task-plan contract](TASK_PLAN.md) and [README design](../../README.md#architecture). / 核心交接、编辑、自动加载观察和显式原生超时续接已实现；第四谓词仅在显式wait_policy下请求，观察不等于成功。人工只读observe现复用原等待且不再付费判断；模板共享profile/service、执行绑定及编辑器已源码实现，学习core也已接通并纳入Main冻结离线回归。不把新图冒充原after，整任务收益未证明。

The internal v2 `assessment_context` freezes round 0–2, original receipt SHA, evidence-set SHA, elapsed milliseconds and the remaining request timeout into authenticated storage. Round 0 uses `[after]`; a later round uses `[after, observation]` with distinct capture IDs/paths and the same window birth identity. Service preparation, provider acquisition/queueing and request preparation consume the same remaining budget. Runtime must separately validate capture provenance, enforce per-step limits and reject late results before adoption; a service result alone is insufficient. / 内部轮次上下文与原回执、证据集、剩余预算共同认证；服务准备、获取 provider 和排队均扣减余量，运行时另查采集来源、单步次数和晚返回，不凭服务结果直接放行。

**Earlier manual+pure-template checkpoint (2026-10-10):** Main's manual+pure-template freeze records1008 passed/1 symlink-permission skip out of1009, zero failures/errors, XML91.700s, stdout91.74s and wall92.968s;1048 Python-file hashes match. A review-found replay-image P2 retains its RED and repair, with bounded source re-review closed. Earlier756/1 and Candidate01 installation/desktop evidence stay historical. This result excludes later template wiring and does not establish new-candidate live acceptance, a package or benefits. Zero paid calls/desktop actions; usage stays12/12 (43,665 input tokens). See the [P2 checkpoint](../verification/ADAPTIVE_P2_SOURCE_20261010.md). / **此前人工观察＋纯模板检查点：** Main人工观察＋纯模板冻结组1008通过/1项符号链接权限跳过（共1009，失败/错误0，XML91.700秒；stdout91.74秒、wall92.968秒，1048文件SHA一致）。重放图像P2保留首败并修复复查闭环；此前756/1与Candidate01为历史，不覆盖后续模板接线或新候选实机，不宣称发布/收益。本次零付费/桌面，额度仍12/12。

### Manual read-only observe (unreleased source) / 人工只读观察（未发布源码）

手动观察仅支持原输入completed且action_executed=True的v2核验等待，暂不支持read_text的False；复用原run/step/execution/wait，逻辑请求先持久占位，相同请求不重截图，未知采集不重派。自动与手动共享最多2次，失败/未知也计数；手动12秒采用期限不重置自动期限，同步capture不能硬中断，晚回复拒绝采用。v3保留原after与assessment_round，追加新图/证据摘要/祖先链；仅最新包可审核，旧包只可读取已认证图像，仍须原wait显式continue。 / Manual observe requires completed original input and action_executed=True at a v2 verification wait; read_text=False is unsupported. It retains the original IDs, persists a logical claim before capture and never repeats identical or unknown captures. Automatic and manual captures share two attempts, counting failed/unknown attempts. The separate12-second manual adoption deadline does not reset the automatic deadline or hard-interrupt synchronous capture. V3 preserves original after and assessment_round, appends evidence/ancestry, permits review only of the latest packet and read-only image retrieval from authenticated older packets, then requires explicit original-wait continuation.

Observe is an explicit Main control, not a Decision disposition or new inference. It cannot authorize input, revise a verdict or automatically continue. MCP `images=after` on its receipt returns the labeled observation's original PNG pixels; logical replay of an older observation authenticates the current chain before reading the older image and never rolls the review packet back. / observe是Main明确控制，不是模型路由或新推理，不能授权输入、判定成功或自动继续。MCP在该回执返回明确标记的新观察原像素；旧逻辑重放先验证当前链再读旧图，不回退审核包。

### Typed condition template profile (unreleased source) / 类型条件模板配置（未发布源码）

共享 profile/evidence/service 与执行计划绑定、编辑器已源码实现；学习 core 也已接通并纳入 Main 冻结离线回归，全部新模板路径未发布、无新候选实机验收或收益结论。下例为可离线校验的非秘密 JSON，使用 [完整动态 record_id 计划](TASK_PLAN.md)中的同一模板身份；这里的 auto 与当前新配置默认一致，但该模板三元身份仍须明确批准，不替用户保存或安装配置。 / Shared profile/evidence/service, caller-plan binding and the editor are implemented in source; learning-core integration is also implemented and included in Main's frozen offline regression. Template paths are unreleased without new-candidate live acceptance or benefit claims. This nonsecret, offline-validatable example matches the linked plan. Auto matches the new-configuration default, but the template identity still requires explicit approval; this example does not save or install a user's configuration.

```json
{
  "contract_version": "decision_profile.v2",
  "mode": "auto",
  "api_key_env": "OPENAI_API_KEY",
  "timeout_seconds": 8,
  "pass_threshold": 0.9,
  "fail_threshold": 0.1,
  "request_cap": 20,
  "auto_conditions": [],
  "auto_condition_templates": [
    {
      "condition_template_id": "detail_record_id_equals_input",
      "revision": 1,
      "template_sha256": "a84a522757c78460d230643f347ca0251fe4ed155810073dd43668b5e1ce5130"
    }
  ],
  "proactive_review": true,
  "review_policy": "adaptive"
}
```

auto_condition_templates 的身份必须同时匹配 condition_template_id、revision 和 template_sha256。auto 下未知、不同修订或不同规则 SHA 的模板零 provider 调用并交 Main；即便渲染后的 condition 在 auto_conditions 中也不回退字符串批准。显式 shadow 可发送付费建议，但不采用结果；off/缺服务不启用判断，完整本地证明仍走原本地路径。 / Template auto approval matches all three identity fields. Unknown/revised/hash-mismatched auto templates return to Main with zero provider calls, without falling back to auto_conditions even when the rendered string matches. Explicit shadow may pay for advice but never adopts; off/absent services do not enable judgment, and complete local proof retains its local route.

condition_snapshot 是可重建的本地认证对象，不是新增 provider 协议。发送给 provider 的仍是原有 v2 payload：具体 condition、绑定图像及既有上下文字段；其中具体条件包含本次参数值。完整快照进入本地请求摘要和认证账本，最终采用须由运行时从原冻结 plan.inputs 独立重算后显式传入 validate_result；重开读取不重新派发。不能凭返回结果自带的快照认证模板采用。 / The snapshot is local authentication material, not a new provider field. The existing v2 payload still sends the concrete parameter-bearing condition, bound images and context. Runtime independently rebuilds the full snapshot from frozen inputs and supplies it explicitly to validate_result; reopening does not redispatch. A returned snapshot cannot authenticate itself.

参数从 R-101 改为 R-202 保留模板身份，改变的是本次条件/source/snapshot 摘要，须新开计划。修改规则文字、参数约束、allowed_states 或 review_policy 则须新 revision、重算 SHA 并明确批准新的三元身份。profile 变更仍须正常关闭后新开会话，不热改旧认证账本。direct decision_check 仍是 literal condition 合同，不接受 condition_binding/condition_snapshot；模板入口为完整 v2 执行计划及已审核学习程序绑定。native_condition 同时保留原 UIA condition 对象，仅替换其语义回退字段。 / Parameter values preserve template identity while changing the concrete snapshot for a fresh plan. Rule changes need a new revision/hash and explicit approval. Profile changes require a clean new session without rewriting old authenticated storage. Direct decision_check remains literal-only; native checks retain their UIA object and replace only the semantic fallback field.

此前1008/1检查点只涵盖人工观察＋纯模板；后续执行接线限定回归325 passed，含实际 DecisionService＋离线 FakeProvider 的A/B输入认证、后端采用、重开零重发及未知模板零调用，不转计为发布、实机或准确率收益。 / The earlier1008/1 checkpoint covers manual observe and pure templates only. The subsequent325-check execution group includes real DecisionService with a fake provider, A/B input binding, backend adoption, reopen without redispatch and unknown-template zero calls; it is not release/live/accuracy evidence.

### Native condition semantic continuation (unreleased) / 原生条件语义续接（未发布）

V2 caller plans may explicitly opt a `native_condition` into semantic assessment. / v2临时计划可显式声明原生条件的语义判断：

```json
{"kind":"native_condition","condition":{"text":"Requested detail","control_type":"Text"},"decision_condition":"The requested detail is visible.","allowed_states":["Requested detail with no modal choice"]}
```

Optional `allowed_states`, `review_policy: always_main` and `wait_policy` reuse the strict semantic contract and require an explicit `decision_condition` or full `condition_binding`. Those semantic fields are mutually exclusive; the native `condition` object stays required. V1 accepts none of these additions. Complete native proof stays local with zero calls. Step-level `always_main` pauses directly; an enabled v2 global policy applies in auto/shadow, while global off preserves the existing local path. / 其他控制项须有decision_condition或完整condition_binding，两个语义字段互斥，原生condition对象仍必填；v1不接受新增项。完整本地证明零调用，单步明确逐步审核直接暂停；启用的v2全局策略在auto/shadow生效，off保持原本地路径。

Semantic continuation accepts only the maintained, fully bound `timed_out` proof after trusted completed input. Every baseline/sample must be valid absent/matched; errors, ambiguity, unknown records, identity/geometry/time/hash mismatches and invalid original frames cannot dispatch a paid assessment. `input_sequence` requires its final search receipt. The original `after_capture_rechecked=false` and receipt remain unchanged; assessment uses the verified original after image. Backend rechecks qualification before adoption, with the existing v2 profile, exact allowlist, budget, owner, original review/continue, finite-observation and late-cancellation gates retained. / 只允许可信原输入完成后的完整维护超时证明；全部记录、身份、几何、时间、哈希和原后图须有效，组合输入必须绑定末次search。坏证据不付费绕过，不把False改True或篡改原回执，最终采用再次重核，既有门禁全部保留。

This path and manual `observe` are implemented and verified offline. Typed-template caller-plan integration is now implemented; learning-core integration is also implemented and included in Main's frozen offline regression. None of these source slices claims new-candidate live acceptance or benefits. / 此路径与人工observe已源码实现并离线通过，类型模板执行计划接线现已实现，学习core也已接通并纳入Main冻结离线回归；均不宣称新候选实机或收益。

Current source derives learning review context from the actual success/failure graph, not definition-list order. Shared nodes appear once with explicit edges, and values stay redacted. Existing multi-step v2 authenticated contexts may differ: finish/cancel on the old frozen runtime and use fresh runs after updating. / 学习上下文按实际分支图生成；共享节点去重、边明确、保留脱敏。旧多步骤v2上下文可能与新投影不同，须用原冻结运行时结束旧运行，更新后新开。

The default owned HTTP transport now uses an absolute monotonic network deadline across all phases/body chunks, preserves connection reuse and cancels without retry. The service also rejects late assessment answers before adoption. It sends `Accept-Encoding: identity` and rejects encoded bodies before reading. Native capture, cold initialization and local persistence are not hard-real-time operations; their actual durations remain separately measured. / 自有HTTP传输共用网络总截止，复用连接但不重试；服务再次拒绝迟到结果。仅接受identity编码，读前拒绝压缩体。截图、冷初始化和落盘仍须分别计量，不能宣称全流程硬实时截止。

2026-10-08，执行 **0.1.2-preview.2** / 学习 **0.1.0-preview.2**。执行与学习共用 `app/judgment`，调用 OpenAI `POST /v1/decisions`（`gpt-6-luna`）。它判断明确条件，不提供点击坐标或动态文本值；视觉定位仍使用当前 Agent、委派 Agent、外部视觉 API 或可选本地模型。 / Execution **0.1.2-preview.2** and learning **0.1.0-preview.2** share the OpenAI Decisions adapter. It checks explicit conditions; grounding and dynamic reading keep their existing providers. Local model weights remain optional.

## Published v1 configuration / 已发布 v1 配置

已发布 preview.3 或明确保留 v1 时，复制 [legacy v1 配置示例](../../configs/decision-profile.legacy.example.json) 到自己的配置目录。API Key 仅放在启动宿主实际可见的 `OPENAI_API_KEY` 环境变量；配置、MCP 参数和管理员连接票据只保存变量名称与文件路径。管理员进程的环境可能不同，缺 Key 会返回 `not_connected`。 / For published preview.3 or explicit v1 compatibility, copy the legacy v1 profile. Put the key only in the named environment variable visible to the actual host, including its elevated process. Never put the key in the JSON, command arguments or relay ticket.

为原 MCP 配置生成命令增加 `--decision-profile C:/path/decision.json`，例如： / Add the profile to the existing configuration command:

```powershell
python scripts/configure_instant_mcp.py --recognition-source agent_current --decision-profile C:/path/decision.json --data-dir C:/path/runtime-data --enable-local-input
```

也可给 `start_instant_mcp.py`、`start_instant_mcp_admin.py` 或宿主传该参数，或使用 `AGENT_GUI_DECISION_PROFILE`；显式参数优先。配置改动需要正常关闭并核实原会话已清理，再新开会话。既有正在运行的宿主不会热重载。当前没有判断 API 设置面板；PowerShell 快捷配置脚本还未提供独立参数，请使用上述 Python 配置入口。 / The normal/elevated MCP launcher and host accept the flag, or use `AGENT_GUI_DECISION_PROFILE`; an explicit flag wins. A changed profile requires a clean new session. Existing hosts do not hot-reload. There is no settings UI or dedicated PowerShell-wrapper option yet; use the Python configuration entrypoint.

| Mode / 模式 | Behavior / 行为 |
| --- | --- |
| 无配置或 `off` | 原流程；零新增判断采图、读图、网络或凭据访问。 / Existing behavior with no decision evidence/network/credential work. |
| `shadow`（v1 配置默认 / v1 default） | 调用并记录建议，仍由 Agent 审核，不自动结算。 / Record advice; keep Agent review. |
| `auto` | 只自动采用 `auto_conditions` 中完全一致的条件，且证据、概率和原回执均有效。 / Adopt only exact allowlisted conditions with valid evidence and original receipts. |

默认阈值 0.9/0.1 只是配置起点，未证明已校准准确率。条件满足且错误/危险概率低才算 success；明确不满足可判 failure；冲突、灰区、拒答、超时、坏协议都保留 uncertain 并交回 Agent。`request_cap` 默认 20：普通执行按整个宿主会话计数，学习按每个 run 计数；动作前后共享各自额度。达到上限不再发送，不自动重试。 / Thresholds are provisional, not calibrated accuracy. Conflicting or inconclusive evidence returns to the Agent. The cap counts execution requests per host session and learning requests per run, shared across phases; reaching it stops new dispatches.

## Execution / 执行

只给需要语义核验的单步附加条件，不要求每次动作调用： / Add a check only where a semantic judgment is useful:

```json
{
  "kind": "step",
  "operation": "execute_recognition_plan",
  "request": {"goal": "Open detail for record R-101"},
  "decision_check": {"phase": "after_action", "condition": "The detail view for record R-101 is open."}
}
```

沿用 `instant_run/instant_submit` 的原 `request_id`；Agent 识图路由还需要原有 `vision_capabilities`。`after_action` 复用动作回执的最终截图，一次请求合并“条件满足”和“可见错误”两个独立判断。`operation_succeeded` 仍只表示输入路线结果；`task_effect_verified` 只有通过原执行/截图/条件绑定与认证的自动结果才能改变。影子、不确定及错误不触发重做输入。轮询只读原结果，不重复调用 API。 / Keep the original execution ID and existing vision-capability declaration. Post-action checks reuse the final receipt image and batch two predicates. Input dispatch and verified task effect remain separate. Polling never repeats the paid call or input.

`before_action` 当前仅支持 `step/execute_recognition_plan` 的真实候选派发边界，合并“前提满足”和“危险效果”判断。自动模式下明确列入的条件必须得到有效 success 才能继续原门禁；API 不能自行授权输入。等待期间窗口、图像、目标几何变化即拒绝派发。没有宿主判断 scope 的直接 HTTP 声明会拒绝，不能冒充已经受保护。`input_sequence`、`form_fill`、独立 `grounding_execute` 尚未提供此附加检查。 / Pre-action checks currently cover the recognition-plan step boundary only. A valid automatic success permits continuing the existing gates, never grants authorization. Changed evidence during the wait rejects dispatch. Batch/form-fill/separate-grounding routes are not covered by this new check.

已发布本地操作路线的自动风险策略仍关闭。新 before-action 路径只在显式检查且服务启用时保留现有作用域内 final-submit/send/confirm/payment 禁止项；不把全局搜索框里的 “Submit search” 当最终提交。这不是全产品安全保证，也不改变未配置判断的原路线。 / The published local route still has automatic risk interception off. This opt-in boundary additionally respects existing scoped prohibited-action classifications; it does not apply a global keyword filter or imply universal safety coverage.

## Published learning integration (v1) / 已发布学习接入（v1）

在正常草稿保存与审核流程中，为步骤设置： / Save and review an explicit step condition through the existing program workflow:

```json
{"verification":{"kind":"agent_judgment","decision_condition":"The detail view for record R-101 is open."}}
```

可同时保留原 `image_check`：本地图像匹配成功仍零 API；只有证据完整、重新计算一致的 `image_not_matched` 才进入语义判断，复用最后一帧，不另采一次。没有图像规则的显式语义检查通过维护接口采集新图；未配置、关闭或缺 Key 的首次语义检查直接返回 Agent。修改条件生成新程序版本，必须重新审核；当前未增加 UI 专用编辑控件。 / Keep an optional local image check. Local success stays zero API; a proven semantic mismatch can reuse its final frame. Pure semantic checks capture through the maintained interface. Changes require review of a new pinned version; there is no dedicated UI field yet.

动态文字读取、输出变量、坏图、错窗、陈旧证据和取消/恢复冲突不会由“是/否”替代。自动采用经过原 Trial 结算，核对 run/step/execution/窗口/证据；不能伪装人工审核，单独声明的 Agent 成功断言仍需满足。已有条件会在图像规则编辑时保留，不会因修改阈值或关闭图像核验而静默丢失。 / Predicates do not extract dynamic output or override invalid evidence, cancellation, recovery or separate Agent assertions. Automatic adoption uses the original Trial settlement and binding checks. Editing or disabling image checks preserves an existing semantic condition.

## Evidence, timing and limits / 证据、耗时与限制

- 已发布 preview.3 的超时约束 HTTP 各阶段与排队；当前未发布源码增加自有传输总截止，见上文。两者都不是包含本地 I/O 的全流程硬截止；均无自动重试、重定向或换模型。 / Published preview.3 uses stage/queue timeouts; unreleased source adds the owned-transport total deadline above. Neither is a hard end-to-end local-I/O deadline; neither retries, redirects or switches models.
- 请求只上传当前步骤明确绑定的 1–2 张图；校验路径位于所属 session、文件 SHA256 和窗口进程身份。启用即会把这些图与条件发往 OpenAI。 / Only bound, verified session images and conditions are uploaded to OpenAI.
- `session/judgments/decisions.sqlite3` 保存发送标记和 Windows DPAPI 认证结果；崩溃/未知发送状态保留，不因重开重新付费。认证结果不代表模型判断必然正确。 / Durable dispatch markers and DPAPI-protected results prevent automatic repeat dispatch after reopening; authentication does not prove semantic accuracy.
- 会话冻结非敏感配置；恢复时核对原条件、回执、截图与认证账本，仅读取原证据，不需要 Key，不重新调用 API，也不修改来源会话。缺失或篡改的记录拒绝恢复。 / Recovery validates the original condition, receipt, image, frozen nonsecret profile and authenticated ledger without a key, new API call or source-session writes; missing or altered evidence is rejected.
- 回执区分 `elapsed_ms`、`http_elapsed_ms` 与服务端 `openai-processing-ms`（若提供），另含实际 tokens 与供应商 request ID。`elapsed_ms` 包含本地准备和发送标记，但在最终结果加密/落盘前结束；完整判断耗时须在 `evaluate` 调用外计时。各层时间有包含关系，不能相加；没有服务端时长就记未知，不把整个网络时间称为推理时间。 / Record service/client/server timings separately. Service elapsed includes preparation and the dispatch marker but stops before final result encryption/persistence; time the evaluate call externally for complete judgment latency. These nested timings must not be added together; unknown server time stays null.
- 集成检查见 [源码验证记录](../verification/DECISION_API_INTEGRATION.md)，本轮新数据实机流程、时间对照和安装范围见 [preview.2 验收](../verification/DECISION_API_RELEASE_ACCEPTANCE_20261008.md)。限定样本包含 API 灰区后交回 Agent 的情况；不能外推通用准确率、尾延迟或总 Agent token 收益。 / See integration and release evidence for bounded fresh GUI cases, timing comparisons and installed scope. A real gray-zone result required Agent review; the sample does not establish general accuracy, tail latency or total Agent usage savings.

协议依据：[OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions)。 / Protocol reference: the official Decisions guide.

## Popup continuation / 弹窗是否可忽略

当前未发布源码在原 recognition-plan 点击边界自动检测同应用前台 popup，包含 `input_sequence` 的 focus 子步。采用 v2 auto profile，并将 `app/execution/popup_decision.py` 的 `POPUP_CONTINUE_CONDITION` 原文加入 `auto_conditions`；两个 v2 示例已包含。宿主不修改已加载 profile。无 popup 不请求；显式弹窗内部目标沿用原路径。 / Unreleased source detects owned foreground popups at the original recognition-click boundary, including input-sequence focus. Use v2 auto and the exact `POPUP_CONTINUE_CONDITION` in `auto_conditions`; both v2 examples include it. Frozen profiles do not reload. No popup means no additional request, and explicit popup targets retain their existing path.

Decision 只判断原动作能否忽略弹窗继续。一次请求绑定原图、候选、窗口身份与 popup 快照；认证为 continue 且等待后证据一致才产生本次内部 guard。需选择、关闭、填写或判断不确定时交回原 Main，不自动处理 popup、不重放输入。配置缺失、shadow/always_main、条件未批准、超时或窗口变化均不能自动继续；既有预算与前动作阈值不变。 / One authenticated assessment binds the screenshot, original candidate and native window/popup identity. Only a fresh continue result permits the original action through existing gates. Popup interaction, uncertainty, unavailable configuration or changed evidence returns to Main, with no automatic input replay. Existing budgets and pre-action thresholds remain.

程序保留父窗 enabled、完整目标未被遮挡、点击点归属、身份及几何复核；Decision 不能让实际被遮挡的目标穿透点击。超出父窗截图的 popup 信息不全，交 Main。该窄分支不代表复合输入已支持任意 before_action 声明。 / Native enabled, occlusion, hit ownership and identity checks remain; Decision cannot authorize click-through. Partly uncaptured popups require Main. This narrow integration does not add arbitrary before-action declarations to batch input.


### 历史点击图 / Historical executed-click view

历史视觉字段可输入、选区和值审核使用真实点击回执绑定的字段裁剪图（当前仅保留输入后文字审核）：包含完整字段与16px周边，每帧只上传一张点击标注crop。原完整图、source SHA、原窗口/点击坐标及裁剪映射本地认证；OCR从未标注原图读取。标记只说明历史实际点击，不证明当前焦点或成功。动作前候选和无字段的独立结果维持各自合同；无可用点击的帧不伪造标记，旧标注整图请求保留历史认证语义。 / Historical visual field usability/selection/value review uploads one marked crop per frame; the current revision retains only the post-input text field check, covering the complete field plus16px padding. Full originals, source hashes, identity and transforms remain authenticated locally; OCR reads unmarked pixels. Historical click markers are not focus/success proof. Candidate/outcome and frozen full-frame contracts retain their own semantics.


### 输入后只核对文字 / Text-only value checkpoint (2026-10-12)

新纯视觉 value 判断只问：目标输入框是否显示规定的 expected_text？Choice仅为文字匹配、文字不符或缺失、文字读不清；不再要求焦点、当前可行性或后续跳转。当前提示词数据只上传目标描述与期望文字，原回执及图像认证仍保留在本地绑定。新条件为 `The target field displays exactly the specified expected text.`，已加入视觉执行示例配置；旧冻结配置/回执及显式native值条件保留原义，新会话需加载更新后的条件列表。 / New pure-visual value checks ask only whether the target displays the expected text, with match/mismatch/unreadable choices. Focus, action feasibility and later navigation are outside this checkpoint. Updated visual profiles allow the new condition; frozen and explicit-native contracts keep their previous meaning.

此前文字判断检查点：462项离线回归通过，8次双视图/单图对照及4次正式默认固定截图重放符合预期；这些是前序整图批次，非本次字段crop实机结论。本次OCR/crop最终536项离线回归与单请求诊断见[新记录](../verification/OCR_FIELD_CROP_20261012.md)，完整浏览器复测仍待执行。 / Earlier full-frame text-only checks passed 462 tests and fixed-frame comparisons. They do not certify this crop increment; see its 536 final offline checks and one replay, with full browser validation pending.
