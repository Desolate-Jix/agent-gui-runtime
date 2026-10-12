# Visual submit binding / 视觉提交绑定（2026-10-13）

Status: the fresh source MDN journey passed, but installed candidate04 failed in its first MDN round at field-value review. Execution 0.1.2 is unpublished and has no independent live acceptance. / 状态：全新 MDN 源码流程通过；安装候选04在首轮 MDN 字段值审核处失败。执行 0.1.2 尚未发布，也未完成独立实机验收。

Failure: after correct visible URL input, the original Enter sometimes reached the browser document. A translation-popup control reproduced the difference; the exact Chromium event is still unknown. Value Decision was correct. / 故障：网址文字正确，但原 Enter 有时送往网页；翻译弹层对照复现了差异，浏览器内部具体事件仍未知，文字 Decision 本身正确。

The common invariant is destination continuity between verified input and submit. Pure visual input now proposes the authenticated field geometry as verified_visual_field, obtains fresh candidate approval, and performs click then Enter through the existing gated recognition API. Value approval alone never authorizes the click. No extra Luna request, UIA read, fixed wait, threshold change, focus-appearance check or automatic replay is added. Standalone press_key and explicit native input are unchanged. / 通用约束是已核验输入与提交的目标连续性。纯视觉输入用已认证字段位置构造新候选，经新一次 Decision 审核后在原点击门禁中连续点击与 Enter；值核验不能独自授权点击。不新增 Luna 调用、UIA、固定等待、阈值修改、焦点外观判断或自动重放。

Each submitted visual input adds one compact candidate Decision. Existing crop/marker preparation remains: one overview/detail image, hollow marker, complete 2× field crop for exact text. Prior per-request token savings are not whole-flow savings; total latency/tokens must be measured in real regression. / 每次视觉提交新增一次精简候选审核，沿用概览＋细节图、空心标记与完整两倍字段裁剪。单次请求 token 收益不代表整条流程收益，须在真实回归统计总耗时和 token。

Receipt: visual_submit.v1 links the original input and value proof to a new click and genuine key_dispatch.v1. No-click rejection, completed click without Enter, partial unknown key dispatch and completed Enter remain distinct. Cancellation/identity/geometry/deadline and one-shot capability checks remain. No final-submit/send/payment permission is added. / 回执绑定原输入、值证明、新点击与真实按键派发；区分未点击、已点击未按键、按键结果未知和完成。原有取消、身份、几何、期限及单次能力约束保留，不增加提交表单、发送或支付权限。

Checks at this offline stage: 231 related checks passed in 15.07 s (visual-submit-offline-final.xml), including the production gated route, settlement, cancellation, no native/OCR reads, and text-only value prompts. The intermediate 147 passed / 7 failed run remains recorded; its fixture lacked the original review context and was corrected without weakening production checks. Later live outcomes are recorded below. / 此阶段离线检查：231 项相关检查在 15.07 秒内通过，覆盖正式门禁路由、结算、取消、无原生/OCR读取及只问文字的提示词。中间 147 通过／7 失败记录保留，已补齐夹具原审核上下文，未放宽生产检查；后续真实结果见下文。

Next: resolve the common visual-value ambiguity between committed field text and inline suggestions, verify both positive and negative controls, then repeat the affected continuous source and installed acceptance before independent acceptance or publication. Keep the first failures and retained browser profile. / 下一步：核清通用视觉值核验中已输入文字与内联建议的边界，用正反例验证后重做相关源码连续流程和安装版验收，再进行独立验收与发布；保留首次失败记录及浏览器资料目录。

Live regression04: the command proxy incorrectly sent the authenticated submit target through grounding again, then duplicate grounding_target arguments raised TypeError before the second maintained input entry. Two Decision and two grounding calls were used; no submit click or Enter occurred. Fixed the shared proxy to pass only the exact internal VisualSubmitTarget through its existing preflight, cancellation, dispatch and receipt path. 92 focused tests passed in 6.93 s (visual-submit-proxy.xml). Original failure/unknown receipts remain; after host shutdown Main normally closed the uniquely owned test window without changing its profile. / 真实回归04：命令代理误把已认证提交目标再次送去定位，随后 grounding_target 重复传参在第二次动作入口前抛出 TypeError。用了2次 Decision、2次定位，提交点击与 Enter 未执行。公共代理已补确切内部能力透传，保留原预检、取消、派发及回执；92项定向检查在6.93秒通过。原失败／未知记录保留，宿主停止后 Main 正常关闭确切拥有的测试窗口，资料目录未改。

## 2026-10-13 Current verified source / 当前已验证源码

manifest18 freezes 608 delivered files (SHA256 4cd4623de3a56761def05e11897941c906304485cb8587778931bd0d22fe1967). The three-address regression05 passed, with 12 Decision and3 grounding calls. A different fresh Bing→search 维基百科 地球→Chinese Wikipedia Earth flow passed its first entire attempt: two automatic rounds, authenticated zero-input cancellation, normal owned-window/host cleanup;20 Decision,7 grounding,23,438 Decision input tokens. Sources stayed unchanged and the retained browser profile/cache were preserved. / manifest18冻结608个交付文件，三次地址回归通过；不同新流程首次整套两轮、零输入取消及正常收尾通过，运行中源码未变，缓存保留。

Evidence roots: D:/AgentReviewAcceptance/execution-012-enter-diagnostic-05 and execution-012-bing-earth-01. Offline:231 checks in15.07s, then92 proxy-related checks in6.93s (overlapping groups, not additive). Regression04 failed because the command proxy repeated grounding and passed a duplicate argument; this is preserved separately from the fixed result. No general accuracy or end-to-end speedup claim. At this manifest18 source freeze, installed candidate, independent acceptance and publication were still pending; later installed results are below. / 原代理漏接首败保留；测试组有重叠，不相加。在此 manifest18 源码冻结时安装、独立验收及发布仍待完成；后续安装结果见下文。不宣称通用准确率或整体提速。


## 2026-10-13 Field-request correction / 字段请求纠正

Candidate03 installed acceptance passed round one but stopped in round two: the correctly entered Chinese query was classified as condition_not_met before Enter. The first failure and normal cleanup remain preserved. The retained profile/cache was not reset. / candidate03 安装验收第一轮通过，第二轮在正确中文输入的字段审核处误拒，Enter 未派发；首次失败与正常关闭记录保留，资料目录和缓存未清理。

The selected fix keeps the original complete 2× marked field crop and asks the literal comparison directly in the single Choice question, for example: `Is the entered text in the input field exactly "维基百科 地球"? Ignore the click marker, icons and insertion caret.` The expected value remains bound to the original authenticated action, JSON-quoted as comparison data, and is no longer repeated in a context block. No focus/empty-field check, threshold change, extra API call or retry is added. / 保留完整两倍字段标注图，把规定文字直接写入本步三选一问题；期望值仍绑定原动作并使用 JSON 引号，不再重复上传上下文，不增加焦点或空框判断、阈值修改、额外请求及重试。

Six retained real fields (Chinese with/without a visible caret, English search, two URLs and a long path), each paired with a wrong-text counterexample, produced 12/12 expected choices using the final production request. HTTP round trips were 163.940–207.980 ms with 375–546 input tokens; the original Chinese false-refusal case changed from 568 to 546 tokens. These are selected-image diagnostics, not general accuracy or an end-to-end speed comparison. Merely cropping tighter, changing wording while retaining an indirect expected_text reference, and strip layouts did not reliably fix the original case; those experimental layouts are not in production. / 六组保留实图正反例 12/12 判断符合预期；HTTP 往返约164–208ms，375–546输入tokens，原中文案例568→546。仅为选定样本，不代表通用准确率或完整流程提速；裁更紧、保留间接引用的问法改写及分段布局未可靠解决原误拒，未纳入正式实现。

Verification at this correction stage: 240 related offline tests passed; new desktop, rebuilt installed and independent acceptance were pending then. Later source and installed results are below. / 此纠正阶段相关离线 240 项通过；当时新流程桌面、重建安装及独立验收尚待完成，后续源码与安装结果见下文。

## Fresh source acceptance after correction / 请求修正后的新流程源码验收

Frozen manifest20 (609 collected files) completed Bing → search `MDN JavaScript Array map` → open the first ordinary MDN Array.prototype.map article on its first full attempt: two rounds in one window/session, authenticated zero-input cancellation, normal owned-window/host cleanup, zero Main repair/retry, unchanged source and retained browser profile/cache. The previous installed Earth failure is still a failure, not relabeled. / manifest20 全新MDN流程首次整套两轮、零输入取消和正常关闭通过；无主Agent修补或重试，源码未变、缓存保留。旧安装版地球流程失败仍保留。

20 Decision requests used 23,176 input tokens; the four field-value requests used 458–547 tokens and 166.822–280.181 ms HTTP (median179.419ms). Seven separate grounding calls include the cancellation probe. These are observed request figures, not complete-task comparative timing. Rebuilt installed and independent acceptance remain pending at this source freeze. / Decision20次、23,176输入tokens；字段4次458–547tokens，HTTP约167–280ms、中位179ms；另7次定位含取消。不是任务总耗时或前后对照，重建安装及独立验收在此冻结时待完成。

## Installed candidate04 first failure / 安装候选04首次失败

The source MDN attempt remains a first-attempt pass: `D:/AgentReviewAcceptance/execution-012-bing-mdn-01/flow-summary.json` records two completed rounds, authenticated zero-input cancellation, normal window/host cleanup, zero automatic retries and a retained browser profile. The installed candidate04 attempt is separate. At `search_mdn_map` in round one, the field showed dark committed `MDN JavaScript Array map` followed by gray inline `guide` and a `Tab` accept badge. The production text Choice rejected the correct committed value (`condition_not_met`, probability 0.76); Enter was not dispatched. `D:/AgentReviewAcceptance/execution-012-bing-mdn-installed-main-01/flow-summary.json` remains `passed=false`, `rounds_completed=0`, `cancel_verified=false`, `automatic_retries=0`; its owned window and host closed normally, with the profile retained and source hashes unchanged. / 源码 MDN 首次整套仍计通过：两轮、认证的零输入取消、正常关窗与宿主收尾、零自动重试，浏览器资料保留。安装候选04是独立首次尝试：首轮 `search_mdn_map` 字段中深色已输入值后出现灰色内联 `guide` 和 `Tab` 接受提示，正式文字 Choice 将正确已输入值误判为不满足（0.76），Enter 未派发。原安装版摘要保留失败、零完整轮次、取消未验证；窗口和宿主正常收尾，资料目录与源码哈希未变。

Read-only diagnostics reused the retained image. `mdn-inline-suggestion-probe/results.json` records the original question rejecting the correct value (0.76 not-met) while falsely accepting an expected value that includes unaccepted `guide` (0.99 met); adding an exclusion sentence still failed both controls. `mdn-inline-suggestion-probe-02/results.json` changed wording and compared full/tight crops: correct-value controls passed, but the `guide` counterexamples still falsely passed (0.94/0.81 met). `mdn-inline-suggestion-probe-03/results.json` tightened the choice descriptions: its full crop falsely accepted `guide`, while both correct-value controls were rejected; the tight crop rejected `guide` but also rejected the correct value. None distinguished both values reliably, and none was adopted into production. These probes are diagnostic API results, not desktop acceptance or a repair. Execution 0.1.2 remains unpublished and independent live acceptance has not occurred. / 只读诊断复用保留原图：原问题误拒正确值，却以 0.99 将包含未接受 `guide` 的错误期望判通过；补充排除句仍未同时判对。第二组改问法与完整／紧裁图使正确值通过，但错误期望仍以 0.94／0.81 误过。第三组收紧选项说明后，完整裁图仍误过错误期望且误拒正确值；紧裁图虽拒绝错误期望，也误拒正确值。三组均未可靠区分正反例，均未纳入生产；诊断 API 回放不等于桌面验收或修复。执行 0.1.2 未发布、未完成独立实机验收。

### Current inline-completion evidence / 当前内联补全证据

Candidate04 did not pass installed acceptance: the typed value `MDN JavaScript Array map` was rejected while the unaccepted gray suffix `guide` could be incorrectly treated as entered. Boundary prompts and folded crops did not fix both cases and were not adopted. The maintained complete annotated ROI stays unchanged. The field-only Choice now asks for Main review when a gray suggested suffix with an acceptance-key hint is visible; ordinary text comparison remains one question/request with its expected literal in the question. No threshold, wait, retry, focus/UIA check, or browser-profile setting changed.

候选04安装验收失败，未发布。生产请求明确把“灰色建议后缀＋接受键提示”交回 Main，不宣称能正确区分其已输入边界；保留完整裁剪标注、不增加请求。最终选定样本：普通字段6组正反例12/12分类正确；同一灰色建议图的3个期望都转 Main（这是接管策略验证，不是3次识字正确）。HTTP约126–258ms，424–597输入tokens；离线9文件243通过。此前宽泛描述误转普通URL、边界/折行方案失败均保留且未采用。新鲜流程及安装验收尚待完成。

### Annotation occlusion and new-flow results / 标注遮字与新流程结果

SQLite source attempt completed both input/search steps, then correctly stopped without clicking: ordinary result links were outside the visible viewport, occupied by Bing summary cards. The unchanged two-round plan lacked a scroll/replan step; the attempt remains incomplete. DuckDuckGo→Rust completed its first three-step round, then stopped in round two after the correct `Rust ownership book` entry: the rendered historical-click ring covered the final letter. No Enter followed; normal owned-window/host cleanup and profile retention passed in both attempts.

通用证据约束：派生标注不能盖住本次要读取的文字。新字段值展示在安全2倍大小范围内，完整原ROI放大后添加外沿坐标刻度，字段内部不画圆环；点击前目标审核不变。不添加 API 或等待，不调整阈值。真实失败图及6组保留字段共14个正反例分类正确，另3个灰色补全样本按声明策略交 Main。每例仍一张图/一个请求，输入377–597tokens；17次HTTP为130–1033ms（中位数约166ms），含一次首请求长尾。该选定样本结果不代表普遍准确率。超尺寸字段保留原显示路线，不宣称其标记布局已改变。后续用全新argparse流程验证，未发布。

### Fresh argparse source acceptance / argparse 全新源码验收

2026-10-13: DuckDuckGo → search `Python argparse documentation` → open the ordinary official Python argparse result passed on its first complete attempt: two identical rounds in one window/session (6/6 steps), authenticated zero-input cancellation and normal window/host cleanup; no Main repair, automatic retry, forced close or profile/cache reset. Evidence: `execution-012-ddg-argparse-01`; frozen 609-file manifest23 SHA256 `ca85163c5bb6bc8a5cde9c04ab74599be5ba3d6dc4a62a555d1d546da4b8a672`. Installed and independent acceptance are still required.

外沿标记的最终生产请求与17个已测wire逐项一致；Main九文件251项离线通过。全新argparse源码首次两轮、取消、正常收尾通过。先前candidate04、SQLite、Rust失败均保留；安装候选05仍需完整验收，未发布。

## 2026-10-13 Independent shortcut false refusal / 独立快捷提示误拒修正

字段Choice只比较规定文字，忽略独立快捷提示，将紧贴文字的灰色未接受补全交Main；完整ROI配外沿刻度，字段像素不被遮挡。19次固定诊断与预设分类符合18次：16个普通正反例全部正确，3个补全样本全部交Main，其中1个选择不满足而非证据不足。HTTP约123–197毫秒、374–594输入token仅为单请求数据，不是任务速度或通用准确率。生产请求与19次实测一致，相关89项离线通过。candidate05 Main安装验收两轮/取消/收尾通过，但独立验收把正确网址旁的独立Tab提示误认补全；候选05不能发布，修订请求待不同新流程和重建安装/独立验收。

The field-only Choice compares the exact requested value, ignores independent shortcut hints, and hands an attached gray unaccepted completion to Main. A single complete ROI with margin ticks preserves text pixels. The 19-request diagnostic matched 18 exact predeclared labels: all 16 ordinary positive/counterexamples were correct; all three completion cases requested Main, although one selected unmet instead of uncertain. HTTP 123–197 ms and 374–594 input tokens are request-only measurements, not task speed or general accuracy. Production wire matches all 19 tested requests; 89 related offline checks passed. Candidate05 Main installed acceptance passed two rounds/cancellation/cleanup, but independent acceptance falsely refused a correct URL beside a separate Tab shortcut. Candidate05 is not releasable; the revised request requires a different fresh source flow and rebuilt installed/independent acceptance.

- Failure / 失败：独立验收首轮正确输入 `https://duckduckgo.com`，未发Enter；原失败与正常关窗/宿主收尾保留。 / The first independent round stopped after correctly typed URL and before Enter.
- Root contract / 根合同：可见字段值与独立浏览器快捷提示不得混同。 / Field-value evaluation must distinguish typed text from a separate browser shortcut.
- Common fix / 通用修复：`text_value_choice_question(field_crop=True)`仅收窄灰色续接文字，单图与认证保持；没有站点词表。 / The common compact field question narrows completion to an attached continuation, without site rules.
- Regression / 回归：新增误拒原图及单字符错误期望，保留中文、路径、网址、灰色补全反例；19个wire逐项比对，API调用0。 / Retained authentic images and wrong-value counterexamples; exact offline comparison against 19 dispatched payloads.
- Safety / 输入约束：未满足与证据不足均交Main，不提交Enter，不改概率阈值、等待、重试、UIA或焦点规则。 / Both non-met outcomes retain review without Enter or automatic replay.
- Evidence / 证据：`execution-012-ddg-argparse-installed-main-01`、`execution-012-ddg-argparse-installed-sol-01`；私有实验 `field-adjacent-completion-probe`。刻度色从旧实验174改为本次实测194，旧实验结果不混记。 / The new marker color matches the tested payload; historical results remain separate.

## 2026-10-13 Fresh Git documentation run / 新Git文档流程

`execution-012-ddg-gitdiff-source-main-01`, manifest25: round1 completed all three steps automatically; round2 opened DuckDuckGo, then stopped before grounding or input for its search step. Original error was `capture_visibility_changed`, not a Decision rejection. The bound window stayed stable; one reported bottom occlusion shrank from `(974,1016,275,16)` to `(974,1024,275,8)` in a 1249×1032 capture, with another region unchanged. The failed frame and occluder identity were not saved, so no specific app or pixel cause is established. Entire acceptance failed; cancellation probe was not reached. Failure cancellation and normal owned-window/host cleanup succeeded; profile/cache retained, no retries.

源码首轮3/3自动完成；第二轮在搜索输入前因截图可见性几何变化停止，未定位、未输入。此停止不是Decision误拒，不计整套通过。日志只证明底部遮挡矩形缩小8px，不能据此确定遮挡软件。正常失败取消与收尾成功，缓存保留。14次已完成Decision、15,876输入token；3次字段值审核HTTP约152–177ms、374–504输入token，全部接受正确值；不能将不完整流程计为整体性能收益。

Pending narrow repair / 待修：only tolerate receding occlusion already covered by the original mask; reject masked candidate points before dispatch, retain all identity/current-point gates, and add no capture retry, delay or API call. New/moved/unknown occlusion remains rejected. / 仅允许旧遮罩已覆盖的遮挡退缩；原遮罩内候选点必须输入前拒绝，新增或移至旧范围外的遮挡仍拒绝，不增加等待或API。修复后使用不同curl文档流程。

## Receding-occlusion contract / 遮挡退缩合同

Only a post-capture occlusion completely contained in the original mask union can reuse the single captured frame. Keep the original mask; reject new/moved/unknown occlusion and any window binding change. Before Decision or input, the common action route rejects a point inside that source mask, with an authenticated not-dispatched receipt. Unmasked ROI routes remain unchanged; unknown masked-ROI mapping is rejected. No additional capture, wait, API request or normal-path PNG decode is added. / 仅后遮挡完全包含于原遮罩并集时保留单次截图，继续使用原遮罩；新增/外移/未知遮挡与窗口绑定变化仍拒绝。通用动作入口在Decision或输入前拒绝原遮罩内点，并认证未派发回执；无码ROI保持既有路线，带遮罩的未知ROI映射拒绝。不新增截图、等待、API或普通路径PNG解码。

Verification / 验证：worker红阶段5失败3通过；Main最终8文件153通过（含损坏路径、坐标/摘要/遮罩篡改、罩内零输入、罩外继续、无图像IO快速路径）；原19份Decision请求离线逐项一致。源码新流程尚待实际验收。 / These checks validate the common capture/input contract; fresh live acceptance remains pending.
