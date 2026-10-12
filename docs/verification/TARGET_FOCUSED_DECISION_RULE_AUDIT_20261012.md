# 目标优先与旧规则审核 / Target focus and legacy-rule audit

日期 / Date: 2026-10-12。未发布源码 / Unreleased source: codex/dev-decision-api。无提交、推送或打包 / No commit, push or build.

## 职责与修改 / Responsibilities and changes

Decision 新鲜度问题只问当前点击点是否仍在可辨认、无遮挡、可用的原目标内；目标外变化仅在遮挡、移位、重定向输入、改变动作含义或需要介入时影响判断。已认证的无关区域在本次单个动作内允许继续变化；保护区实际像素、窗口几何、遮挡元数据或范围外变化仍使旧证据失效。新内容未逐次重新接受语义审核，此容忍不跨动作缓存。 / The freshness predicate checks whether the current click point remains inside the same identifiable, unobscured and usable target. Outside changes matter only when they obscure or move the target, redirect input, change the action or require intervention. Authenticated irrelevant-region changes may continue within this one action; protected pixels, window geometry, occlusion metadata or changes beyond that region still invalidate evidence. New content is not individually re-reviewed; tolerance is never cached across actions.

已认证的合并 Decision 通过后，原生遮挡检查只覆盖实际点击像素；原候选框、目标语义、截图绑定及新鲜度检查保持完整。没有合并审核或审核未通过时不取得该范围。弹窗存在本身不否决动作；真实点遮挡、失效窗口、禁用父窗、取消、超时、权限和单次派发约束继续生效。 / After authenticated combined Decision approval, native occlusion checks cover the actual clicked pixel, while preserving the full candidate box, semantic target, capture binding and freshness checks. Missing or rejected combined review never obtains this scope. Popup presence alone is not a veto; actual point occlusion, invalid identity, disabled parent, cancellation, deadlines, authority and single-dispatch rules remain enforced.

| 旧规则 / Previous rule | 结论 / Outcome |
| --- | --- |
| 无关新闻、文字、动画也否决新鲜度 / Unrelated news/text/animation veto | 改为目标与当前动作优先的条件，同步profile / Target-focused predicate and matching profile |
| Decision通过后必须整页停止变化 / Entire page must stop changing | 本次认证区域内可继续变化，保护区和范围外变化仍拒绝 / Allow continued same-action reviewed-region changes; retain protected/outside checks |
| 分离变化联合外接矩形跨目标就拒绝 / Union change rectangle crosses target | 删除5行推断，以实际保护区像素和Decision为准 / Removed five-line heuristic; use actual pixels and Decision |
| 通过Decision后仍三次检查完整候选框遮挡 / Three full-box gates after approval | 认证路径改传实际点击像素；原候选bbox不缩小 / Pass actual click footprint only on authenticated route; preserve candidate bbox |
| 同一弹窗存在即拒绝 / Same-popup presence veto | 当前v3已没有；同次Decision判断，不新增请求 / Already absent in v3; same combined request |
| 等待旧browser readiness / Legacy browser-readiness wait | 普通direct_visual已跳过；显式学习/复用保留 / Already bypassed for ordinary direct_visual; explicit learning/reuse retained |

保留：窗口/进程身份、实际点命中与遮挡、父窗enabled、前台、候选坐标绑定、取消、期限、单次派发、权限与最终提交门禁。popup事实变化与完整入帧约束仍保护Decision证据绑定。无Decision及旧兼容路径没有被全局放宽。 / Retain identity, actual hit/occlusion, enabled parent, foreground, coordinate binding, cancellation, deadlines, single dispatch, authority and final-submit gates. Changed popup facts and incomplete popup evidence still invalidate reviewed evidence. No global relaxation of no-Decision or compatibility routes.

阈值0.80、接管规则和生产请求上限20未改；旧冻结profile不热更新。 / Threshold0.80, review policy and production cap20 are unchanged; frozen profiles do not hot-reload.

## 实测与限制 / Live evidence and limits

- 修复坐标后的两次尝试：候选均1.00通过，旧新鲜度分别.76/.61拒绝。根目录 / Root: D:/AgentReviewAcceptance/visual-flow-coordinate-fixed-1791722527107。
- 同图只读API新条件：.98/.97通过；故意错误点0.00、接管.95，拒绝。HTTP 2.808/2.471/2.133秒。记录 / Record: 上目录的 target-focused-readonly/summary.json。这些是模型评分，不是准确率 / Model scores are not measured accuracy.
- 仅改提示词实测：Decision .99通过，旧末端静止规则拒绝。保留 / Preserved: D:/AgentReviewAcceptance/visual-flow-target-focused-1791723086548/target-focus-summary.json。
- 有界末端规则实测：Decision .99、末端freshness=valid；随后旧全框popup检查拒绝。bbox(76,43,2300,34)与popup[2154,76,2498,242]仅相交222×1像素；点(1225,59)在弹窗外。记录 / Record: D:/AgentReviewAcceptance/target-bounded-1791723532659/target-focus-summary.json。
- 最后旧回执仍action_executed:null：首次按下前的False未完整持久化，保留unknown，不自动重放。cancel_requested阻止同宿主关窗；宿主正常停止、cleanup_verified=true、exit0后，用项目维护关闭接口核对原launch完整身份，仅正常关闭本次测试窗口，owned-window-cleanup.json为true。 / Preserve the unknown original receipt; no replay. After verified host shutdown, the maintained close primitive rechecked the original owned-window identity and closed only that test window.

该旧规则清理阶段只完成离线验证；后续三次实测及修复见下方新增记录，完整Google/java链仍未通过。 / This cleanup checkpoint initially had offline coverage only; the subsequent three trials and repairs are recorded below, with full acceptance still incomplete.

## 故障合同 / Runtime invariant

Failure：Decision认可目标，程序因无关变化或远处bbox边缘相交仍拒绝。 / Semantic approval was overridden by unrelated change or remote overlap.
Root invariant：候选范围不是输入足迹，联合变化外接矩形不代表实际像素变化；语义交Decision，程序检查输入事实。 / Candidate extent is not input footprint, and a union bounding box is not actual changed pixels.
Fix location：共用action_review_dispatch.py、target_freshness.py、visual_action_conditions.py及app/api/action.py；没有Edge/Google/地址栏特判。 / Common runtime, without app/site-specific rules.
Regression：分离变化、目标单像素、alpha、mask/几何、Decision拒绝、错误点、真实遮挡、无Decision。 / Regression covers these positive and rejection boundaries.
Safety impact：移除重复保守否决，允许已审核的大目标在远处部分被遮挡；真实点及原授权门禁保留。认证区域内后续内容不逐次语义审核，是本次单动作的明确容忍范围，不跨动作复用。 / Allows reviewed partially covered large targets while retaining actual-point and authority checks. Continued content inside the reviewed region is not individually re-reviewed and is never cached across actions.

## 实际离线验证 / Executed offline checks

日志目录 / Evidence: .superpowers/sdd/2026-10-11-visual-execution-decision-flow/。

- target-focused-boundaries-red.xml: 5 failed /42 passed；target-focused-final-green.xml: 159 passed /7.55s。
- fresh-disjoint-red.xml: 2 failed /1 passed；fresh-disjoint-green.xml: 52 passed /2.29s。
- click-visibility-red.xml: 3 failed /2 passed；click-visibility-green.xml: 5 passed /1.16s。中间trace断言修正失败也保留 / Intermediate test-assertion failures are retained.
- old-rule-cleanup-main-green.xml: 267 passed /9.72s。覆盖合并审核、新鲜度、几何、条件配置、popup、无派发回执和视觉默认路径 / Covers review, freshness, geometry, profiles, popup, no-dispatch receipts and visual defaults.

历史阶段有重叠，不累计为总覆盖。最终267项与独立新增5项不重叠。 / Historical checkpoints overlap; the final267 and separate new5 are distinct.

## 下一步 / Next

首次按下前拒绝的持久化证明已补齐，旧unknown不回写。当前先查焦点Decision不确定，再复验完整浏览器链、同会话连续使用、取消及清理。 / Durable pre-down rejection proof is repaired without rewriting old unknown receipts. Next diagnose uncertain focus assessment before validating the complete browser flow, continuity, cancellation and cleanup.

## 2026-10-12 输入前拒绝回执修复 / Pre-input rejection receipts

首次鼠标按下前的 nonmodal/guard 拒绝现在由输入层生成 `click_input_boundary.v1`，包含窗口身份、矩形、原坐标、按钮、次数和明确的 `button_down_attempted:false`；公共 API 与派发前冻结的请求逐项核对后，才持久化 `not_dispatched / action_executed:false`。已尝试按下、双击第二击失败、缺失或错绑定证明仍为已输入/未知。没有放宽输入门禁，也不回写旧 unknown 记录。 / Before the first mouse-down, nonmodal/guard refusal now produces a bound `click_input_boundary.v1` proof. The API independently matches its window, geometry, points, button and count against the frozen request before persisting no-dispatch. Attempted input, second-click failures, missing or mismatched evidence never become no-input. Gates and old unknown receipts are unchanged.

故障合同：输入层明确拒绝且未开始 down 的事实，必须沿公共派发、回执、计划取消传递；不能只因进入 click 方法而变成未知。修复位于共用 input_controller、recognition_dispatch、action API，无网站特判。 / Invariant: a proven pre-down rejection must remain no-dispatch through persistence and cancellation. Entering a click method alone is not evidence of attempted input. The fix is shared runtime code, without a site adapter.

离线：首次 RED 14 failed/1 passed；本轮相关139 passed/3.81s，Main集成166 passed/12.67s。两组有重叠，不累计。证据：`popup-zero-dispatch-freeze.json`、`popup-zero-dispatch.diff`、`popup-zero-dispatch-green.xml`、`popup-zero-main-regression.xml`，均在上述日志目录。 / The scoped worker suite and Main integration suite passed; overlapping counts are not summed.

首次新浏览器实测：`D:/AgentReviewAcceptance/receipt-fixed-1791725702719/batch-summary.json`。Decision和末端门禁通过，真实地址栏点击成功；输入前 check_focus 抛 KeyError，尚未填写网址/搜索。partial-focus票据保持 action_executed:true，未重放。正常停止宿主（cleanup_verified、exit0），核验原launch身份后只关闭本轮窗口。历史unknown文件SHA保持不变。 / First new live attempt passed Decision and final gates and clicked the address bar, then raised KeyError in focus checking before typing. The partial receipt remains executed; no replay. The stopped host and owned window were cleaned up, preserving historical unknown evidence.


后续修复 / Follow-up: 首次实测的确切异常为 `KeyError: capture_id`。`read_visual_focus_snapshot` 现复用 `decision_frame` 归一化原始 post-action 截图，再进入有界字段读取；不改旧票据、不伪造输入结果。现场边界回归先复现3失败，再由字段/部分输入74项通过（5.69s）、Main字段/公共视觉/输入序列78项通过（3.36s）。错误hash与窗口身份在读取前仍被拒绝。首次Main验证命令曾引用不存在测试文件而未执行用例，保留 `field-capture-main.xml`；更正命令的结果为 `field-capture-main-green.xml`。 / The live KeyError came from missing capture_id normalization. The common focus reader now uses the existing decision_frame contract, preserving historical receipts and integrity validation. Three reproductions failed before repair; scoped74 and Main78 suites then passed. A mistyped initial Main test path ran no tests and is retained separately from the corrected successful run.


第二次复测 / Second retry: `D:/AgentReviewAcceptance/receipt-rerun-1791725956210/batch-summary.json`。地址栏点击成功，但原生字段reader在resolve_field阶段返回text_field_target_not_writable，尚未调用焦点Decision、未键入。项目接口只读复现诊断为5层Pane、没有解析出字段；并非读取到readonly属性。证据 `focus-read-diagnostic.json`。宿主exit0且清理确认，本轮自建窗口已核对身份正常关闭；保留partial回执。 / The second retry clicked successfully but failed before typing or focus Decision. A read-only project diagnostic found five Pane ancestors and no resolved field, rather than a read-only attribute. Host and owned-window cleanup succeeded; the partial receipt is retained.


公共分类修复 / Classification repair: `_resolve_field` 穷尽原有四级父链但未找到字段时，改发 `text_field_control_unavailable`；仅显式visual使用已有不可用分支转Decision，传统UIA输入仍拒绝。读取到readonly/password/disabled、窗口错配等反证不转视觉放行。下游ROI文字读取按需调用已有RapidOCR，并真实记录engine_reused；失败、超时、非单条、低于.99或文本不匹配仍不采用。无全窗扫描、额外模型定位或新准备器。 / A bounded unresolved-control lookup is distinct from an observed non-writable field. Only the existing explicit visual path consumes this unavailable result; legacy input and known negative evidence remain blocked. Existing ROI OCR initializes lazily and records actual reuse, retaining deadlines, exact text and confidence checks.

回归 / Checks: `field-control-red.xml` 10 failed；冷启动边界 `field-control-cold-guard-red.xml` 3 failed/1 passed；`field-control-green.xml` 196 passed/6.04s；Main `field-control-main-green.xml` 180 passed/4.03s。各阶段覆盖有重叠，不累计；本轮4文件diff/SHA在 `field-control.diff` 与 `field-control-freeze.json`。 / Counts overlap and are not summed. Frozen file hashes and exact slice diff are retained.


## 本轮最终实测结论 / Final live outcome

第三次新连接：`D:/AgentReviewAcceptance/receipt-flow-final-1791726428537/batch-summary.json`（Decision摘要在同目录 `decision-summary.json`）。候选条件1.00、目标新鲜度0.97通过，真实点击地址栏；焦点Decision condition_met0.54、needs_agent_review0.44、visible_error0.21，verdict uncertain、disposition review_required。目标字段描述已传入动作上下文；尚无证据可把这次不确定判成纯提示词或其他区域干扰的确定根因，未降低阈值或强行采用。仍未输入Google网址、未搜索java、未打开首链接。 / The third fresh run passed candidate1.00 and freshness0.97 and clicked the address bar. Focus assessment returned uncertain/review_required (condition0.54, review0.44, visible_error0.21). The field description was supplied. The exact cause of model uncertainty is not yet established; no threshold reduction or forced adoption was used. URL entry, Java search and first-result navigation were not completed.

三次失败均保留，未把后续修复当首次成功；三个宿主cleanup_verified=true、exit0，自建窗口按原launch身份正常关闭，旧unknown票据SHA未变。Main最终相关回归180项通过、diff check通过；输入拒绝修复此前166项通过，测试集合有重叠。未提交、推送、发布或打包，不宣称性能/准确率收益。 / All failures are retained. All three hosts exited cleanly and owned windows closed after identity verification; the old unknown receipt remains byte-identical. Main final relevant180 and earlier receipt166 checks passed with overlapping coverage. No commit, push, release, build or performance/accuracy claim.

## 焦点补充诊断 / Additional focus diagnosis

同图提示词、字段类型、标点图、ROI和前后截图的只读对照均未形成可采用的焦点通过结论，未把这些实验改入生产，也未降低阈值。它们是失败诊断，不能作为准确率或实际输入成功证据。 / Read-only prompt, field-kind, point-marked image, ROI and before/after experiments did not establish an adoptable focus result. No experimental prompt or threshold change was adopted.

全新探测发现“还原页面”弹窗的Button确有键盘焦点，地址栏Edit没有焦点。通过维护的Luna+Decision动作接口点弹窗X后，弹窗关闭导致原动作后截图不可得；保留该原回执为action_executed=true、不可自动重试。随后选回父窗口，新截图确认弹窗消失，原生两路读取均确认Edit获得焦点。不能据此反推上一轮0.54的唯一原因。 / A fresh probe found keyboard focus on the Restore pages popup Button, not the address-bar Edit. A gated Luna+Decision X click closed the popup; its original post-action capture was unavailable. Preserve action_executed=true and no automatic retry. A fresh parent capture and both native focus reads then confirmed the Edit held focus. This does not retrospectively prove the sole cause of the earlier 0.54 score.

证据 / Evidence: `D:/AgentReviewAcceptance/focus-native-probe-1791727467236/`，含前后native-focus记录、popup-recovery-summary.json和batch-summary.json。探测窗口正常关闭，宿主cleanup_verified=true、exit0。 / The owned probe window closed normally; host cleanup verified, exit 0.

### 点击足迹修正后实测 / Point-footprint rerun

视觉字段按点击点1×1读取，snapshot只要求实际控件包含该点；完整视觉候选框保持。Main相关回归189 passed / 4.14s（focus-point-main-green.xml）。新host配置最初因测试助手重复追加auto_conditions被拒绝，零API、零输入；单独保留后修正测试配置。有效实测位于D:/AgentReviewAcceptance/focus-point-fixed-1791728139265：焦点点击已执行，总输入序列13.692s后停止；Decision焦点0.52，未输入URL、未搜索。

Luna定位4.752s；三次Decision分别3.273/1.522/0.770s（含各自预处理），前后截图0.149/0.124s。这些计时存在包含关系，不可直接和其它inclusive字段相加。复测后查到GetFocusedElement返回有焦点Edit，而ElementFromPoint返回同窗Pane，故focus_value_snapshot没有进入请求。尚未宣称自动完整通过。 / Native focus and point lookup disagree: the former finds the focused Edit while the latter returns a containing Pane, so the snapshot was absent. Preserve this failed trial and its timings; do not treat it as full-flow success.

通用优化依据 / General optimization references: [OpenAI latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization) 建议减少串行请求、并行独立步骤和采用合适的确定性方法；[Microsoft direct element access](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-obtainingelements) 支持直接读取焦点且提示遍历树成本；[UIA cache](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients) 支持批量属性读取及UI变化后刷新。结合本轮证据，先修错误停点，再合并重复模型往返；不能把截图开销当作主要耗时，也不能缓存跨动作授权。 / Applied recommendation: repair false stops first, then consolidate redundant round trips; screenshot time is not the dominant measured cost and action authority must never be cached across actions.

### 当前焦点直接读取 / Direct focused-field read

新增read_focused_at_point：仅点击后直接读当前焦点，两次核对原窗口/进程/创建时间、原点、可写/非密码、焦点和实际RID/type/bbox/value/selection一致性；不调用ElementFromPoint或树遍历，legacy reader未改。Main201 passed / 4.10s（focus-direct-main-green.xml）。 / Post-click reads now use the current focused field directly, with two consistent bound reads and unchanged negative checks; no point lookup or tree scan.

D:/AgentReviewAcceptance/focus-direct-fixed-1791728520528实测中真实focus_value_snapshot已送达，但现有只看可见图像的条件返回predicate_refused，仍无URL输入。该失败保留。原生焦点语义只读对照：正确地址栏.97、review.01；错误目标（网页中央搜索框）0、review.99。HTTP .488/.454s；两次仅诊断，无授权动作。 / The native snapshot was delivered, but the old image-only predicate refused. A read-only evidence-context comparison separated the true target from an intentionally wrong goal. These two scores are not an accuracy benchmark or full-flow success.

### 原生焦点说明与真实输入 / Native context and actual typing

原生焦点专用provider分支验证完整快照和唯一afterframe绑定后，说明原生焦点事实；没有snapshot时保留原图像路径，错误绑定在HTTP前拒绝。Main164 passed / 6.95s（focus-context-main-green.xml）。 / Only fully bound native focus evidence receives the clarified prompt; absent evidence retains the old route and malformed binding rejects before HTTP.

D:/AgentReviewAcceptance/focus-context-fixed-1791728732141：第一次candidate Decision .50，零输入回执正确保存为not_dispatched/action_executed=false，并返回blocked_before_dispatch审核包。Main看原截图后经同会话resume_pre_dispatch显式恢复一次，候选.92、新鲜度.98、焦点.89通过；已真实输入Google URL，尚未Enter。随后发现回执只保存text_length/text_sha256，而value proof还要求明文text，故visual_field_input_binding_invalid；保留该失败和Main介入，不算全自动或任务完成。 / The first attempt was correctly classified as no-dispatch. One explicit Main-reviewed resume passed candidate, freshness and focus checks and typed the URL. Post-type proof then rejected the intentionally redacted request because it incorrectly required plaintext. No Enter was dispatched; this is not full-flow success.


## 输入回执摘要绑定与目标外遮挡 / Typed-receipt binding and outside occlusion

2026-10-12：生产输入回执会删除明文，只保留text_length与text_sha256；旧视觉值核验却只接受明文，导致网址已输入后报visual_field_input_binding_invalid。现在接受原请求一致的完整摘要，若明文与摘要同时存在则两者都必须一致。并未把明文写回回执。Main相关检查90 passed/3.96s；输入链四文件合并回归315 passed/4.57s（不与前序计数累加）。真实后续Enter仍待验证。 / Production audit receipts redact text, keeping length and SHA256. Value-proof binding now accepts a complete matching digest pair and requires agreement if raw text also exists; no plaintext is restored. Main checks passed90 cases, then315 cases in a consolidated four-file input suite. Live post-value Enter remains pending.

本次typed-binding-fixed-1791729233842在点击前被unexplained_occlusion_change拒绝，action_executed=false，正确保留为零输入；Decision候选1.00。遮挡从右下角两块变为一块，均远离地址栏保护区，未进入既有目标外变化Decision复核。宿主正常finish，exit0，cleanup_verified=true；本轮原有浏览器继续保留供修复后复测。 / The next attempt correctly recorded zero input after an outside-target occlusion metadata change. Candidate Decision scored1.00, but this branch never reached the existing relevance review. The host finished cleanly; the owned browser remains for retesting. Evidence: D:/AgentReviewAcceptance/typed-binding-fixed-1791729233842/batch-summary.json.


目标外遮挡修复已完成：Main101 passed/5.47s，worker69 passed/2.45s，覆盖重叠不累计。目标/anchor遮挡仍拒绝，末端新mask不容忍。重测在13.795s完成focus步骤，已越过候选/目标外复核/焦点；随后type在首个键盘事件前因光标闪烁拒绝。两张实图唯一像素差异为[281,49,282,69]，1×20；原type receipt错误标为result_unknown，但typing_dispatch所有阶段not_started且events为空。此新缺陷待源码修复，不将整个序列改成零输入（focus点击确已发生）。 / Outside-occlusion repair passed101 Main and69 overlapping worker checks. Target/anchor occlusion and final new masks remain rejected. Retest completed the focus step in13.795s, then refused before keyboard input on a1×20 caret blink. Its type receipt incorrectly classified the untouched typing operation as unknown; the whole sequence still includes a real focus click. Evidence: D:/AgentReviewAcceptance/target-occlusion-fixed-1791729770637/batch-summary.json.


键盘零派发回执已补齐 / Keyboard no-dispatch receipt repaired: local_direct_step仅接受同次原API路由私有issuer/owner/scope的响应，冻结请求/窗口/几何并核对响应摘要及4阶段not_started；持久type_text_no_dispatch.v1由recognition_dispatch再次核对，任意字典、跨调用重放、缺证据、已selection或粘贴均不能降为零。原序列已发生focus click仍保留true。Main92 passed/2.58s；worker13文件379 passed/10.33s（覆盖重叠，不累加）。原始失败未改，尚待新宿主实测。 / Only an invocation-bound response from the original internal API route can issue the proof; persisted request/window/geometry/response bindings and all untouched dispatch stages are verified again by consumers. Forged dictionaries, cross-invocation reuse, missing evidence and attempted input retain unknown/executed status. Existing focus clicks remain true. Main92 and worker379 overlapping checks passed; original failure receipts remain untouched.


## 2026-10-12 后续现场与光标合同 / Later live evidence and caret contracts

keyboard-freshness-fixed-1791730924231已自动完成Google网址输入、值检查、Enter和首页效果核验；原输入序列18.719s，末尾Decision0.281s，可测合计约19.000s。搜索java首败4.352s，Main看图后的单次恢复仍失败4.698s，两次均为target_pixels_changed且零点击；全图唯一差异为[911,473,912,490]，即1×17光标。两次失败及323.919s Main诊断空档独立保留，不把空档算模型推理。该会话3 Luna+7 Decision。 / URL navigation succeeded automatically, followed by two zero-click search refusals on a1×17 caret difference. Preserve both failures and the323.919s caller diagnostic gap separately from model time.

修复后目标/anchor变化进入既有一次双帧Decision，最终只接受审核过的状态；第三种目标像素、新遮挡或拒绝均不执行。target-states-red.xml为5个预期失败；target-states-first-green.xml保留旧断言不符合新合同的1失败；更新为模型拒绝负例后target-states-green.xml为176 passed/4.97s。 / One bounded two-frame review handles target changes; final exact reviewed states, rejection and occlusion tests passed176 cases. Earlier red/fixture-contract failures remain separately recorded.

target-states-fixed-1791732336450复测已focus/type成功，Enter前字段复核predicate_refused（HTTP0.352s），原按键接口误记unknown；未重放Enter。cancel/continue因此保留unknown票据并阻止新start，随后正常finish宿主。该不是慢API或阈值问题。原生双帧事实与adapter“only visible evidence”措辞矛盾已复现；新增严格双快照校验与证据说明，条件和阈值不变。native-field-context-red.xml9失败；green151 passed/4.17s。后续实测与按键证明结果见最新收尾段。 / The next run typed but its pre-Enter freshness predicate refused, exposing missing key no-dispatch evidence and contradictory image-only provider wording. Unknown receipts were preserved and never replayed; cancellation conservatively blocked a new plan. Native-context repair passed151 checks, without changing the predicate or thresholds.


按键与部分结算修复 / Key and partial settlement repair: app/core/key_dispatch.py、input_controller.press_key、execution/local_keyboard_action、local_direct_step、recognition_dispatch以及input_sequence_partial已闭合原调用私有证明；Main整合13文件376 passed/14.76s（complete-input-main-green.xml），worker最终7文件131 passed/8.33s，集合有重叠。完整前缀加零Enter可cancel到cancelled；删除证明仍保留pending。双帧provider补充避免把本次有序字段比较误判成缺少持续视频时序证据，最终相关176 passed/5.50s；视频行为不变。 / Main integration passed376 checks; worker131 overlap. Proven zero-Enter partial failures cancel cleanly, while missing proof remains pending. Field-specific ordered comparison is separated from generic ongoing-video temporal requirements.


keyboard-complete-fixed-1791733123956首步因新分支关闭原有外围动画容忍而拒绝：两次Decision均1.00，末端目标像素已稳定，只有外围新闻区继续变化。已删除该错误限制；第三种目标状态仍拒绝，新增组合负例/正例。target-outside-combination-red.xml保留1失败5通过，green为85 passed/3.17s。 / The new branch incorrectly disabled existing outside-animation tolerance after a reviewed target change. Removed that restriction while retaining rejection of a third target state; the combination regression passed85 cases.

target-outside-complete-1791733773570已自动完成Google首步19.605s（sequence19.307s + final Decision外层0.298s），随后搜索框点击成功但check_focus原生读取失败5.480s；java/Enter和首结果未执行。实际2 Luna + 8 Decision请求，非模型慢响应造成停留。原始错误被包装为InputSequenceInterrupted而丢失诊断及focus-only证明；当前无法断言原拒绝为Text/Pane暂态或readonly，单独只读检查显示字段正常。宿主已finish、cleanup_verified=true、exit0；原浏览器保留用于后续验收。 / The latest run navigated automatically but failed the initial native search-field read after clicking. Original exception wrapping lost the exact cause and focus-only proof. A later read succeeded, which does not establish the cause. Host cleanup succeeded; the owned browser remains for retesting.


视觉check_focus已原样保留真实TextFieldReadError及白名单诊断，只有真实read_visual_focus_snapshot异常才签发focus-only部分失败证明，assess/issue异常不会冒充原生只读失败。Main174 passed/5.48s。独立键fixture晚导入捕获mock路由导致的2失败已修复：单文件4、原两文件128、键/type42通过；不修改生产门禁迁就mock。 / Visual focus preserves typed native errors; only the real read boundary issues the existing partial proof. Isolated fixture import pollution was repaired without production changes.

native-focus-diagnostic-1791734312780中原生焦点读取通过；focus7.742s、after_click Decision0.524s后，Ctrl+A已完成，但相同像素的两幅独立PNG被内容摘要生成同一capture_id，after_selection在派发模型前报visual_field_selection_frame_not_fresh，未粘贴java。保留该部分输入unknown原回执；finish/cleanup成功。修复缺省capture身份为规范artifact路径+摘要，同文件稳定、显式ID保留、fresh gate不删除；空字段在完整原生双读身份/值验证通过后无文字需要选中，省去该选区Decision。空值红测1失败2通过；Main最终8文件220 passed/9.81s（capture-selection-main-final.xml）。先前main-green命名文件实际1失败219通过，原因是读到了worker写入前版本，保留不覆盖。 / The next live run passed native focus but stopped after Ctrl+A because content-only IDs conflated separate captures with identical pixels. Artifact-bound default IDs and a strict native-empty-value selection case are now covered; no input or old receipts were rewritten.


full-browser-closure-1791734666617新窗口首步在点击前因Decision provider/contract error停止（10.513s focus，provider4.544s；旧服务未保留transport/HTTP/protocol细分，不可追认）。Main经原review票据显式续跑一次，focus10.936s、type1.032s完成且值匹配；Enter前仅[281,49,1,20]光标差异，native身份/值/选区一致，Decision却condition0.42、needs_review0.15，Enter零派发耗3.767s。该次不是无干预首轮通过；cancel仍cancel_requested，正复现部分输入消费者遗漏。host finish/cleanup成功，测试窗口暂保留。 / First attempt stopped before clicking on an unclassified provider/contract error. One explicit Main resume typed and verified the URL, then rejected Enter on a1×20 caret difference. Preserve both results and the unresolved cancellation classification; this is not an unattended first-pass success.

已增service provider_error_code精确白名单，保留固定transport/protocol/大小/closed或合法HTTP状态；不透传任意异常文本、密钥或URL，不改变处置。164项离线通过，旧宿主故障不能用新字段追认。 / Sanitized provider diagnostics passed164 checks; original decisions and retry policy remain unchanged.


局部字段细节已进入同次Decision请求（两张原图+各自无标记局部图，不增加时间帧或请求次数），Main239 passed/6.20s；旧2图数量断言已更新并保留一次review/双capture限制。异步failed投影与returned同样验证完整部分证明，worker110项绿；真实target-detail-full-1791735258901中Google自动完成，search_java首次原生诊断证实同窗Pane暂态，现正确terminal failed（settled2/success1），不再unknown。按此加入仅首次同窗Pane/Text的≤250ms、≤11次只读焦点采样，真实字段仍双读全部原检查；Main291 passed/11.03s，原错误及fixture红测保留。 / Same-frame details and asynchronous failed-terminal proof handling are verified. The live search refusal now exposes a transient Pane and settles as known failure. Bounded first-focus sampling preserves all final native checks.

focus-ready-full-1791735743967在Google focus/type之后停止：原生actual_text与expected_text均为https://www.google.com，完整绑定valueSHA/长度22/选区22,22，但after_type Decision仅0.41。Main看原图确认文本正确；adapter的value分支仍使用only-visible提示，遗漏了已有原生值事实说明。该诊断正在修复，不对旧判断改分或重写回执；宿主已正常finish。 / The next run exposed missing native-value guidance in the provider despite exact bound value evidence. Preserve its .41 refusal and original receipts; the host finished normally.


### 原生输入值提示修复 / Bound native value explanation

最后字段值核验补充严格原生证据说明：只对完整 snapshot 合同，核对捕获/原图 SHA/窗口与字段身份/四处文本/值 SHA 和长度/派发回执引用后，告诉 Decision 使用已读取的完整值判断相等，仍检查目标、遮挡和可见矛盾。没有提高概率或修改阈值。新增41项专测；worker相关300项通过，Main受影响集成198项通过（5.92s，native-value-main-final.xml）。

Fresh native-value-full 首次运行12.209s在地址栏点击前拒绝，两个Decision均condition=1，但末次画面变化检查action_review_freshness_retry_exhausted。回执已正确为failed + action_executed=false + blocked_before_dispatch，不是unknown。Main查看维护接口新截图后，记录一次resume_pre_dispatch；首轮失败保留，恢复结果待补。 / Strict bound-native-value context added without threshold or probability changes. The fresh first attempt refused before input despite two positive model decisions; it was correctly classified as a known pre-dispatch failure. One explicit, evidence-linked Main recovery is recorded separately.


恢复结果 / Recovery outcome: native-value-full 的一次明确恢复耗时27.934s，Google首步成功，搜索框已成功键入java，输入后的native value Decision=.98。按Enter前，Google建议列表展开使字段底边样式变化；旧字段变化条件限定only caret blink or focus presentation，Decision=.08而未派发Enter。完整前缀已知+Enter未派发被正确归为failed终态（settled2/successful1），未再挂unknown。宿主finish cleanup_verified=true；窗口保留供新冻结源码复测。此结果不是三步成功。


首点击新帧拒绝的精确复算 / Exact first-click recheck: 原帧到审核帧目标内0差异，外围动画185678像素，bbox[425,300,1037,604)；审核帧到最终帧，地址栏新增[108,49,109,69)的20个光标像素，外围原区域继续185830像素动画。遮罩始终右下同一区域，无新mask。最终目标第三态未覆盖于两张审核图，现有规则拒绝；这是保留的易用性限制，不是模型低分，也不是本轮已修复的unknown分类错误。 / The final frame introduced a20-pixel caret absent from both reviewed target states; unchanged outside animation and mask were not the root cause. This strict final-state limitation remains, separately from the repaired receipt classification.


### 后续公开路径 / Continued public path

field-target-full 在google步骤最终按键前字段复核为.76，低于.80而确定未派发Enter，已知failed。另起明确Main接管计划，使用页面Google搜索按钮后点击首个普通结果，两步18.939s，实际打开 https://www.java.com/zh-CN/；末步模型condition=0/error=.92/review=.99，原截图却显示Java | Oracle正常首页。Main通过review/continue原公开合同复核结算，两步completed；这是明确人工模型接管，不是自动通过。

Main发现原末步条件要求从单张结果图判断“来自第一个搜索结果”，混入不可单帧观察的来源事实。最后试验保留Luna首结果定位和点击前Decision选择，结果条件改成目的网页主内容可见且不是Google结果、加载或浏览器错误；不将来源选择重复交给后图推断。新增字段freshness专用问题解释原生连续事实并保留两项原条件；人工crop边缘不等于UI裁切。Main受影响88项通过（2.47s），模型原始.76仍不提升。 / Main-corrected result evidence is retained separately; final trial uses an observable destination-state predicate, while the first-result selection remains bound to the actual click evidence. Native freshness questions retain original conditions and raw model probabilities.


complete-visible-result 最后完整三步复测13.381s仍在首步Enter前拒绝：after_type=.95，而只变化1×20光标的freshness=.06；native绑定相同。专用问题没有证明提高实测准确率，不能宣称修好了Decision稳定性。随后转向严格本地caret事实核验而非继续调prompt/降低阈值。该次Enter未派发、原步骤failed，宿主已finish并保留证据。 / The dedicated wording did not establish reliable model freshness judgments; the exact narrow caret transition is the next local invariant to verify.


### 有界光标快径与最后遗漏 / Bounded caret path and remaining receipt gap

字段内差异1×20不能代表整图只有光标。对complete-visible-result两张真实原图回放，整图差异bbox[70,49,2232,354]，因此严格快径正确返回false，未用它绕过下拉变化。新快径只在原Decision认证、native identity/value/source/折叠selection连续、已知mask集合一致、整图仅控件内部完整均色细竖线时免掉重复freshness API；其他情况保留原流程。Main214项通过（6.76s）。

caret-native-final完整复测24.341s：Google首步成功；search_java聚焦完成，但before type回调以visual_field_freshness_requires_review拒绝，四个typing派发阶段均not_started/events[]。现场缺少上层采纳所需的私有issuer证明，仍进入unknown等待。本轮据此补齐该真实遗漏，旧JSON不作授权/分类捷径，原件不改。 / The strict caret helper correctly rejects the historical whole-frame change. The latest live run exposed an unissued private zero-typing proof despite no keyboard stage starting; fix the issuer path rather than reclassifying old JSON booleans.


更正最后遗漏的层级 / Correction of the last gap: 进一步检查完整local_receipt，实际已带type_text_no_dispatch.v1、phase=not_dispatched、action_executed=false；缺口在聚焦成功+键入零派发这一组合的消费者分类，不是issuer没有产出。上段早期推断保留为排查历史；后续修复限定为采用已验证的原证明，整序列仍action_executed=true（聚焦确实发生），不能假称整步无动作。 / The local receipt already contains the private proof. The missing case is a completed focus prefix plus an authenticated undispatched typing suffix in the shared sequence classifier.


### 最终收尾 / Final closeout

2026-10-12未发布源码：已修复“聚焦完成、键入尚未派发”被误记为unknown；严格采用原私有未派发证明，保留已发生的聚焦动作，真正未知和历史回执不改。Main相关99项回归通过（7.08s）；有界光标/字段相关214项通过（6.76s，覆盖重叠，不累加）。真实浏览器已输入Google网址、搜索java并打开Java官网；最终恢复计划4/4完成，但需要Main重新规划及末步review/continue，不能算全自动通过。恢复四动作38.336s到审核等待、含Main结算74.558s，均不含此前失败和准备。Enter路径仍有Decision误拒，尚无连续免接管成功证据。最后宿主cleanup_verified=true、exit0，测试窗口按完整身份正常关闭，冻结源码hash一致。未提交、推送、打包或发布。 / Unreleased source fixes the missing completed-focus/zero-typing classification using authenticated private proof, preserving the focus action and genuine uncertainty. Main checks:99 passed(7.08s) and214 overlapping caret/field checks(6.76s). The live browser task reached the Java site; the recovery plan completed4/4 through explicit Main replanning and final review/continue, not automatic acceptance. Four recovery actions took38.336s to review wait or74.558s including Main settlement, excluding prior failures/preparation. Enter freshness refusals and reliable intervention-free execution remain unresolved. Host cleanup and owned-window closure succeeded; frozen source hashes match. No commit, push, build or release.

根因与修复 / Root cause and fix: input_sequence_partial遗漏phase=type且completed_steps=[focus]的严格零派发分支；新增type_not_dispatched_verified，验证原命令、两条完整前缀/后缀回执、文本摘要、窗口/字段身份和私有证明。通用输入序列适用于浏览器和Windows字段，不是java/Google特判。没有降阈值、增加输入权限、重写旧unknown或把已开始输入降为零。只读回放将本轮原失败识别为已知部分失败，原文件hash不变。

最终证据 / Final evidence: D:/AgentReviewAcceptance/final-button-flow-1791737942461；session-fd8cfb78da88421293a22fe493680b35。原last-plan14.482s在Google Enter前已知失败；last-recovery-plan四步38.336s到末步审核。最后Decision condition=.68/review=.83/visible_error=0；Main查看绑定原始after截图确认https://www.java.com/zh-CN/主内容已加载，再公开review/continue，4/4完成。74.558s包含Main查看与结算，仍不是完整首次任务时间。测试窗口9114504/PID41384由native-value-full的final-launch所有，核对完整native identity后正常关闭；最终宿主finish cleanup_verified=true/exit0。

Main最终分类回归：python -B -X utf8 -m pytest -q tests/test_input_sequence_type_partial.py tests/test_input_sequence_focus_partial.py tests/test_input_sequence_search_partial.py tests/test_type_text_no_dispatch.py tests/test_recognition_no_dispatch.py，99 passed/7.08s，type-partial-main-final.xml。字段/光标最终214 passed/6.76s，caret-main-final.xml；两批覆盖重叠，禁止相加。全套测试、独立验收、安装包测试未运行。

计时从2026-10-11 13:31:29 UTC至最终任务回执17:01:34.243 UTC为3小时30分5.243秒，包含全部开发、诊断、测试和Main停顿；这次排查耗时过长，不能归因于API响应或用最后短路径掩盖。后续优化和资料见EXECUTION_PRACTICALITY_20261012.md。
