## 2026-10-13 Popup/Enter control / 弹层与回车对照

本次 Decision 用法的当前回归：170 passed in2.93s（decision-usage-current-main.xml），覆盖候选裁剪、生产请求、Choice、字段放大与文字比较。一次测试命令因误写不存在的文件名未运行任何测试，已用实际文件名完成上述检查。曾尝试“同一工具栏弹层一律前置处理”的提示词草稿，独立审阅指出其会扩张为无证据拦截，已精确撤回且未调用 API；choice_contract 与 manifest16 哈希一致。/ Current Decision-usage regression:170 passed in2.93s. An initial command referenced a nonexistent test file and ran no tests; the corrected invocation passed. An unverified toolbar-origin blocking prompt was withdrawn before API use; choice_contract matches manifest16.

三次窄诊断都在第三次地址输入后未跳转。诊断03记录：网址已正确显示，浏览器内部焦点在 Ctrl+V 后、Enter 前从 Edit 转为 Document；原生前台未变，修饰键已释放，Enter 已插入输入流。输入前原图存在 Edge 翻译弹层。/ Three narrow runs failed at the third address submission. In diagnostic03, the correct URL was visible but internal focus moved from Edit to Document after paste and before Enter; native foreground and modifier states remained valid.

同一 manifest16、同一保留资料目录的对照增加一个经门禁的明确关闭弹层步骤，随后原输入与 Enter 一次成功；最后输入焦点保持到 Enter。四步、11 次 Decision 和4次定位全部完成，窗口/宿主正常关闭，零自动重试，缓存未清理。/ With the same source and retained profile, explicitly closing the popup through the gated action path before the unchanged final input succeeded. All four steps and normal cleanup completed with11 Decision and4 grounding calls, no retries or cache changes.

证据根：D:/AgentReviewAcceptance/execution-012-enter-diagnostic-03 与 execution-012-enter-popup-diagnostic-01。这支持弹层相关失焦，尚未证明浏览器内部具体事件；关闭弹层属于诊断干预，不是通用修复，也不计首次全流程或两轮验收。文字 Choice 和最终页面拒绝均正确，不降低阈值或让模型猜焦点。需收敛公共输入契约后再完成新流程、安装与独立验收；build03和发布仍未执行。/ This supports popup-related focus loss, without proving the browser's internal event mechanism. The intervention is diagnostic, not a generic fix or unattended acceptance. Text Choice and final-page rejection were correct. Resolve the common input contract before new-flow, installed and independent acceptance; build03 and publication remain pending.

## 2026-10-13 Keyboard dispatch evidence / 按键派发证据

新增通用层只读键盘诊断，记录原 SendInput 的键值、flags、返回数量、前后 foreground/GUI active/focus/caret 句柄及修饰键状态。Enter 成功回执带该诊断，Ctrl+A/V 只留日志；不读文本，不激活、不加门禁、等待、重试或模型请求。这只能证明派发及采样事实，不证明目标已消费按键。/ Common read-only diagnostics record native dispatch and window/modifier snapshots, without text access, activation, extra gates, waits, retries or model calls. Dispatch evidence is not proof that the target consumed the key.

Main:8个相关模块159 passed in7.02s，keyboard-dispatch-main.xml；只读采样100次均observed，中位0.006ms、P95 0.0209ms、最大0.1288ms（仅采样，不含日志）。下一步只复现地址栏输入到Enter，作为诊断，不计新流程验收。/ Main passed159 relevant checks;100 read-only samples measured0.006ms median and0.0209ms p95, excluding logging. The next narrow Enter reproduction is diagnostic only, with no acceptance credit.

## 2026-10-13 Bing–IANA B1 / 连续运行仍未通过

第一轮三个步骤均由运行时和 Decision 自动完成；第二轮正确填入 https://www.bing.com，字段 Choice 通过，但 Enter 前后原图 SHA 相同，页面仍为 IANA。结果 Choice 返回 condition_not_met（.84，met .10，insufficient .06），这次拒绝正确。只完成 1/2 轮，独立零输入取消覆盖未达到，不能计整套通过。/ Round 1 completed all three steps automatically. Round 2 entered the requested URL and passed value judgment, but Enter produced no observed navigation. Decision correctly rejected the unchanged IANA page; only 1/2 rounds completed and dedicated cancellation coverage was not reached.

原始证据：D:/AgentReviewAcceptance/execution-012-bing-iana-01，manifest15（606 files，417456b96de7c93c60a768e5f05b05c71e97a3acd80b3112af49498357ee8401）。本轮窗口和宿主正常关闭，同一浏览器资料和缓存保留，源码哈希未变。/ Owned window and host closed normally; the retained browser profile/cache and source hashes remain intact.

当前未能确定 Enter 的根因：代码和回执没有显示输入后再次激活；pressed:true 仅表示派发调用完成，不能证明地址栏消费了按键。下一步补只读按键派发证据并做窄复现，不改变 Decision 阈值、不增加固定等待、不自动重试。修复后按用户要求换新流程完成连续验收，再构建和发布。/ The Enter root cause remains unknown. Add read-only dispatch evidence and a narrow reproduction, without weaker thresholds, fixed delays or automatic retries. Build03, installed/independent acceptance and publication remain pending.

# 视觉执行与 Decision：源码验证 / Visual execution and Decision source verification

当前源码 / Current source: 2026-10-12程序重复像素否决已清理，374项相关离线回归通过；本轮未实测。见[专门记录 / Evidence](PROGRAM_DUPLICATE_VETO_CLEANUP_20261012.md)。下方真实测试属于此前源码。 / Live history below predates this cleanup.


日期 / Date: 2026-10-11；更新 / Updated: 2026-10-12
状态 / Status: **源码回归通过；真实任务经Main接管完成，全自动连续验收未通过 / Source checks passed; live task completed with Main intervention, automatic continuous acceptance incomplete**

2026-10-12未发布源码：已修复“聚焦完成、键入尚未派发”被误记为unknown；严格采用原私有未派发证明，保留已发生的聚焦动作，真正未知和历史回执不改。Main相关99项回归通过（7.08s）；有界光标/字段相关214项通过（6.76s，覆盖重叠，不累加）。真实浏览器已输入Google网址、搜索java并打开Java官网；最终恢复计划4/4完成，但需要Main重新规划及末步review/continue，不能算全自动通过。恢复四动作38.336s到审核等待、含Main结算74.558s，均不含此前失败和准备。Enter路径仍有Decision误拒，尚无连续免接管成功证据。最后宿主cleanup_verified=true、exit0，测试窗口按完整身份正常关闭，冻结源码hash一致。未提交、推送、打包或发布。 / Unreleased source fixes the missing completed-focus/zero-typing classification using authenticated private proof, preserving the focus action and genuine uncertainty. Main checks:99 passed(7.08s) and214 overlapping caret/field checks(6.76s). The live browser task reached the Java site; the recovery plan completed4/4 through explicit Main replanning and final review/continue, not automatic acceptance. Four recovery actions took38.336s to review wait or74.558s including Main settlement, excluding prior failures/preparation. Enter freshness refusals and reliable intervention-free execution remain unresolved. Host cleanup and owned-window closure succeeded; frozen source hashes match. No commit, push, build or release.

本节为最终状态，下方保留先前检查点。 / This final status supersedes historical checkpoints below.

## 范围 / Scope

初阶段源码离线完成后，用户明确授权有界桌面/API实测；首步未派发输入，后续同图调用属于Main故障诊断，不是正常闭环。当前只收尾源码/文档，不追加API、桌面、安装发布；保留首次失败。 / Later approval superseded the initial deferral. Subsequent same-image calls are diagnostic overhead; this closeout adds no API/desktop work or release.

- 工作树 / Worktree: `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`
- 分支 / Branch: `codex/dev-decision-api`
- 证据 / Evidence: `.superpowers/sdd/2026-10-11-visual-execution-decision-flow/`
- [完整流程图 / Diagrams](../superpowers/specs/2026-10-11-visual-execution-decision-flow-design.md)
- [实施计划 / Plan](../superpowers/plans/2026-10-11-visual-execution-decision-flow.md)

## 已接通 / Source integration

| 路径 / Path | 当前行为 / Current behavior |
| --- | --- |
| 用户任务 / User task | v3 冻结 goal、完整计划、当前/剩余步骤和最终 completion；不将最后点击当作完成。 / Freeze the goal, full plan and final completion condition. |
| 定位与前置审核 / Grounding and review | Luna → Runtime自动叠框/青色点 → 原图+标图同一次Decision；框内语义与点可操作/无遮挡、安全、需Main分别判断，无新时间帧或额外Main往返。 / One request includes original and marked candidate, with separate feasibility, safety and intervention predicates. |
| 配置及预算 / Configuration and budget | 实际配置、许可、余额先检查；同一 attempt 共享单调截止，取消/迟返不产生新输入。 / Preflight before paid grounding; one deadline and cancellation boundary. |
| 新鲜度 / Freshness | 原文件完整 SHA + 当前目标/锚点核对；最多1次双帧相关性审核，后续未解释变化转 Main。 / Full artifact integrity and scoped target checks, with one conditional reassessment. |
| 视觉字段 / Visual fields | 原焦点 click → 认证焦点 → 有界全选证明 → 填写 → 精确值核验 → 可选搜索 Enter。 / Ordered focus, selection, one typing dispatch and exact-value proof. |
| 恢复 / Recovery | 可信零输入才允许新 attempt；恢复动作独立票据；已完成前缀和首次拒绝保留，部分/未知不重放。 / Only proven no-input can resume as a new attempt; recovery receipts are separate. |
| 最终完成 / Completion | 最终完整条件与末步相同时复用证明；否则 Main 只读审核，无额外动作。 / Reuse identical final proof or request read-only Main review. |
| 可选并行 / Optional parallelism | scene_precheck 默认 off，数据并行不授予坐标权限，不免计费。 / Scene probing defaults off and cannot authorize a candidate. |

关键源码包括 `action_review.py`、`action_review_dispatch.py`、`target_freshness.py`、`visual_field_proof.py`、`candidate_annotation.py`、`visual_action_conditions.py`、`task_plan_intervention.py`，接入原宿主、动作API、runner及Client/MCP，未建立第二套执行器。 / Shared contracts and annotation integrate into the existing runtime.

## 实际验证 / Actual verification

初阶段源码组合：**1534 passed，147.27秒，exit0，stderr 空，768个源码/测试/配置文件 SHA 前后一致**，0失败/错误/跳过。证据 `final-offline.xml`、`final-offline.stdout.log`、`final-offline-result.json`、`final-offline-source-{before,after}.json`。与后续窄检查分开，不重复累加。 / The initial1534-pass aggregate and stable hashes remain separate from later focused checks.

Main 使用 `D:/agent-gui-runtime/.venv/Scripts/python.exe -X utf8` 执行证据目录中的 `run_final_offline.py`；它只调用列在 `final-offline-test-list.json` 中的57个相关 pytest 文件，保存命令、XML、stdout/stderr 和测试前后源码/测试/配置 SHA。模型和原生输入在测试边界替换；公开联调经过实际 Client → MCP → task-plan/命令队列和维护逻辑，未启动真实桌面宿主。 / The recorded Python harness runs 57 selected offline modules and preserves the exact command, logs, XML and before/after hashes. Providers and native input are replaced at boundaries; public integration uses real client/protocol/queue logic, without a live desktop host.

首轮组合：**1533 passed / 1 failed，135.53秒**。唯一失败是历史 agent 状态回读夹具缺少父命令记录；实际图像身份门禁正确拒绝。修复只补测试中的真实状态命令绑定，不放宽生产校验。首轮保存在 `final-offline-first*`，不覆盖成首轮通过。 / The first aggregate had 1533 passes and one incomplete status-image fixture. Production correctly rejected missing command identity; only the fixture is repaired. Original results remain separate.

关键修复及首败记录 / Key failure evidence:

| 首败 / Failure | 修复 / Repair | 记录 / Record |
| --- | --- | --- |
| Decision 等待期间 job 取消仍可能点击 / Cancellation could still click | 取消回调传到原 owner 和输入 scope，取消后零派发 / Propagate cancellation into owner dispatch | `parallel-cancel-owner-red-valid.xml` → `parallel-cancel-final-green.xml` |
| 已审核动画区域被当成未来变化许可 / Reviewed region authorized future changes | 最后帧仍变化则暂停，不用旧 mask 放行新文本 / Reject newly unreviewed change | `main-animation-review-red.xml` → `main-animation-review-green.xml` |
| 可变窗口对象自比较漏掉身份变化 / Mutable identity alias | 冻结原 handle/PID，不比较同一可变对象 / Freeze original handle/PID | `main-identity-red.xml` → `main-identity-green.xml` |
| selection 图像格式/尺寸边界漏拒绝 / Selection frame validation | 生成、采用与键盘复核共用静态 PNG/窗口尺寸校验 / Validate PNG and geometry throughout | `field-green-freeze.xml` 及 `field-freeze.json` 指向的 RED |
| v3 接受未支持的视觉追加 / Unsupported visual append | 启动校验提前拒绝，v1/v2与显式target保持 / Reject before queueing | `recovery-visual-default-red.xml` → `recovery-visual-default-green.xml` |

子任务177、164、210等结果覆盖互相重叠，**不累加**。首次缺模块/夹具错误和真正合同失败分别保留；最终以 Main 冻结组合为准。 / Worker counts overlap and are not added together. Setup/fixture errors are distinguished from reproduced contract failures.

附加文档检查：保存的 v3 JSON 示例通过实际 validator，新 profile 通过 DecisionProfile 校验（scene_precheck=off，request_cap=20）；维护变更执行 CRLF-aware 的 `git -c core.whitespace=cr-at-eol diff --check` 通过。 / The documented v3/profile examples pass maintained validators; scoped CRLF-aware diff checks pass.

## 后续授权实测与诊断 / Later authorized live attempt and diagnosis

首轮地址栏前置审核零输入拒绝13.827s（Luna HTTP6.811s、Decision2.735s）；取消等待及维护close/finish成功，host exit0，窗口已清理。原始首败保留在 `D:/AgentReviewAcceptance/visual-flow-20261011-1791715074185/first-assessment.json`、`first-input-terminal.json`。 / The first attempt refused before input; cancellation and cleanup succeeded, with original evidence retained.

| 同图只读诊断 / Same-image diagnosis | condition / unsafe / review | 旧before=.90下结果 / Result under old0.90 |
| --- | --- | --- |
| 修正before时态，原图 / Before-tense correction | .06 / 0 / .15 | 未采用 / Not adopted |
| Main人工拆问：可见/点在目标/弹窗不挡 / Manual visibility/point/popup probes | 各condition 1/.94/.99，各review .15 / separate predicates | 诊断开销，不是正常流程 / Diagnostic overhead |
| 原图+标图长问句 / Annotated long prompt | .07 / 0 / 0 | 未采用 / Not adopted |
| 简短框/点问句 / Short box-and-point prompt | .68 / 0 / 0 | condition_gray |
| 最终框内语义，原目标 / Scoped semantics, original target | .86 / 0 / 0 | condition_gray，adopted=false |
| 同图同框同点，目标改为页面中部搜索框 / Wrong-target counterfactual | 0 / 0 / .99 | 语义不匹配拒绝 / Mismatch rejected |

最终pair：正例HTTP2204.8221ms、total2981.8056ms、input8704；反例HTTP1524.6031ms、total1704.1912ms。原始 `D:/AgentReviewAcceptance/visual-flow-20261011-1791715074185/annotation-scoped-pair/summary.json` 与同根目录 `batch-summary.json` 记录累计10/20=Luna1+Decision9、unknown0。单例分数不等于准确率，未真实点击或完成Google→java→首结果及重复流程。 / Raw pair and batch records retain usage/timing. Isolated scores establish no accuracy or autonomous completion.

自动标图保持原尺寸/坐标和原hash、旧回执兼容，原图+派生图同一次请求，无新时间帧或额外Main往返。真实2560×1400图离线渲染158.829ms。原图单次4977tokens/HTTP1604.839ms，双图长提示单次8751tokens/HTTP2163.678ms；单样本不能宣称速度或成本收益。 / Annotation preserves original integrity and request count; recorded render/HTTP/usage samples establish no performance benefit.

提示词最终 **337 passed/6.43s**（`scoped-candidate-prompt-main-green.xml`），先前335项及RED1failed/8passed等保留。用户随后批准可选v2 `before_action_pass_threshold=0.80`；首次RED9failed/7passed（字段未实现），实现后 **257 passed/5.37s**（`before-threshold-green.xml`），不与337/1534累加。默认None保持旧profile摘要；显式新配置使用.80，共享pass=.90/fail=.10、危险/加载、转Main及after阈值不变，旧票据不能按新profile采用。未追加API/桌面；旧.90下的.86未采用不追认为实机放行。 / Separate threshold RED/GREEN preserves legacy defaults and other gates; old receipts cannot be re-adopted under a new profile. New0.80 is offline-verified only.

## 明确限制与计划调整 / Limits and design adjustments

1. **真实速度、准确率和 Google→java→首个结果尚未由本轮证明。** 离线通过不等于动态网页实测通过。 / This batch does not establish live speed, accuracy or the original full search flow.
2. 持续动画仍可能耗尽一次相关性复核而转 Main；已审核区域不允许未来任意新内容。第一版没有自动 Luna 重定位重试，Main 对可信零输入建立新 attempt。此项收窄原计划中的自动重定位，不宣称持续动画已解决。 / Continued animation can still require Main. Automatic re-grounding is deliberately absent in this slice; reviewed regions are not future authorization.
3. 首版视觉输入仅支持可读普通字段的替换。精确值需有界 UIA 或已经预热的 ROI OCR；冷 OCR、不可读内容、密码、追加、任意提交均不作为支持路径。首按键前未解释的 caret/字段变化也可能暂停。 / Visual input supports replacement only; exact value needs a bounded read or prepared ROI OCR. Unexplained caret/field changes can pause.
4. 视觉输入需要额外焦点/值请求，全选最多再1次；不能把普通 click 的1–2次请求当作完整输入组合账单。实际总耗时和 token 待实测。 / Compound input adds separate focus/value and possibly selection calls; click counts are not full-input cost.
5. v3 新语义显式选择；不热改旧计划/冻结 profile。无 Decision 保留旧兼容路线，新路线缺条件/服务明确退回审核，不假装同等自动化。 / Existing plans/profiles keep their meaning; missing service/permission is not silently upgraded.
6. 原生 API 同步调用不能被单调时间硬中断；截止后拒绝采用，保存真实回执，远端已发送请求仍可能收费。 / Deadlines reject late adoption; they cannot hard-interrupt synchronous native calls or undo provider charges.
7. 尚未构建、安装、发布新候选，也未安排外部 Agent 实机验收。 / No new packaged candidate or external live acceptance exists.

## 下一步 / Next step

用户此前暂缓实测已被后续授权取代。当前不追加API；下一步核对Luna框偏上与候选定位/坐标，不靠反复调词或单例凑通过。完整原失败链路、同会话连续覆盖及独立验收仍未完成，未安装发布。 / Later approval superseded deferral. Inspect candidate geometry before further acceptance; prompt retries and isolated scores cannot replace complete and continuous coverage. No installation or release occurred.

## 0.80新会话实测 / New-session0.80 live test

2026-10-12 新0.80阈值实测：新Edge首步在地址栏点击前拒绝，condition=.64、unsafe=0、review=.03，零输入；Google/java/首结果未执行。首步15.412s（Luna HTTP8.714s、Decision HTTP2.375s），仅2次API请求。取消、窗口关闭与宿主finish均成功。证据 `D:/AgentReviewAcceptance/visual-flow-threshold80-1791718878302/summary.json`，保留原始框图，不把此前.86回放当实测成功。 / New0.80 live test refused before the address-bar click: feasibility.64, danger0, review.03; zero input and no completed flow. The first step took15.412s, including8.714s grounding and2.375s Decision HTTP. Two requests; cancellation and owned-window/host cleanup succeeded.


## 点击点版本离线验证 / Point-only offline verification

2026-10-12：候选 Decision 的问题改为“点击标记的中心是否落在指定可见目标内部”；派生图只画青色点击环/十字，不画矩形框。原图仍同请求上传。候选bbox仅保留于原绑定及坐标校验；0.80阈值、安全及接管规则不变。354项离线检查通过（6.64s），已用上轮截图验证点图，未新增API或桌面实测。此前.64失败属于框图版本，原始证据保留。 / Candidate Decision now asks whether the click-marker center lies inside the specified visible target. The derived image shows only the cyan point marker; the original remains in the same request. Bounding-box metadata is retained for binding and coordinate validation. Threshold0.80, safety and review rules are unchanged.354 offline checks passed in6.64s; the point preview uses the prior capture, with no new API/desktop test. The earlier.64 failure belongs to the box-rendering version.

证据 / Evidence: `point-only-red.xml`（4 failed/40 passed）；`point-only-green.xml`（354 passed/0 failed/0 skipped）；`point-only-preview.png`。覆盖原矩形边缘像素不变、标记以外原像素不变、同一点更换bbox不改变派生图、实际服务一次请求包含原图和点图、旧票据及阈值兼容。 / Checks cover untouched former borders, unchanged pixels outside the marker, bbox-independent rendering, actual-service image composition, and receipt/threshold compatibility.

## 2026-10-12 坐标尺度审计 / Coordinate-scale audit

- 失败：原图地址栏可见外接范围约 `(76,44,2298,32)`；Luna 返回 `(63,36,1890,27)` 和点 `(1008,49)`，框整体偏小、偏上。 / Failure: the visible original-image address bar is approximately (76,44,2298,32); the returned box is (63,36,1890,27) with point (1008,49).
- 已核实：保存的预处理记录为原图2560×1400、scale1；离线重走 `_prepare_api_image` 生成完全相同的原PNG。候选、pre-click与Decision沿用同一点；窗口rect为(0,0,2560,1400)，无ROI。未保存完整历史HTTP请求体，因此离线重建不冒充历史抓包。 / Verified: preprocessing records no resize, and offline preparation reproduces the original PNG byte-for-byte. Candidate, pre-click and Decision preserve the point; the window origin is zero with no ROI. This is reconstruction, not a historical wire capture.
- 根因假设：若按2500个32px patch预算且无额外边长上限，图像将缩为2106×1152；对应反映射得到bbox约(76.58,43.75,2297.44,32.81)、点(1225.30,59.55)，与原图高度吻合。官方通用文档说明服务端可能缩图，但本次未取得gpt-6-luna专属尺寸规则或服务端实际预处理尺寸，故仍是强证据假设。 / Root-cause hypothesis: a 2500-patch budget without a dimension cap predicts2106×1152; mapping back closely matches the visible target. Luna-specific processing dimensions remain unconfirmed. Source: https://developers.openai.com/api/docs/guides/images-vision
- 修复位置与通用性：若对照确认，应在外部视觉适配层显式控制提交尺寸并按实际尺寸回映，覆盖所有应用；不写地址栏专用补偿或硬编码1.215倍。当前未修改生产源码/配置。 / Fix location if confirmed: provider image preparation and geometry restoration for all applications, not browser-specific offsets or a fixed1.215 multiplier. Production code/config is unchanged.
- 回归：`pytest -q tests/test_external_grounding_api.py tests/test_vision_grounding_contract.py tests/test_agent_grounding_target.py tests/test_capture_observation_geometry.py`：102 passed/1.28s。本轮审计脚本与JSON、JUnit位于 `.superpowers/sdd/2026-10-11-visual-execution-decision-flow/coordinate-mapping-*`。 / Regression:102 relevant offline checks passed; the saved audit verifies original bytes, dimensions, recorded point continuity and the geometric hypothesis.
- 安全与限制：零真实API、零桌面动作、阈值和动作门禁未变；实际DPI线程状态和最终点击未验证。原点(1008,49)仍在地址栏可见范围内，不能把Decision .64或整个任务延迟全部归因于此偏移。下一步用相同保存图比较原尺寸与显式缩图后的定位；保存原始模型输出及实际提交尺寸，再决定默认策略。 / Safety and limits: no API requests or desktop actions; gates unchanged. No live DPI/click validation. The original point is still inside the address bar, so this does not fully explain Decision.64 or end-to-end latency. Next compare original and explicitly resized inputs using the same saved image, retaining raw outputs and sent dimensions before changing defaults.

## 2026-10-12 坐标修复与真实API对照 / Coordinate fix and real API comparison

2026-10-12：Luna 默认 profile 已设置 `max_image_edge:1600`，复用既有显式缩图和按实际宽高回映；每次定位仍只调用一次模型。真实同图对照中，原尺寸复现尺度偏移，缩图后地址栏两次回映点为(1224,60)/(1225,59)，右侧小按钮点为(2446,180)。174项相关离线检查通过；共4次Luna API请求、零桌面输入，尚未验证点击或完整浏览器流程。自定义profile及已运行宿主不自动改变，需新连接加载；安装器未更新。 / The Luna default profile now sets `max_image_edge:1600`, reusing explicit resize and actual-dimension coordinate restoration with one model call per localization. Same-image API comparisons reproduced the original scale mismatch and restored address-bar points to(1224,60)/(1225,59), plus a right-side button to(2446,180).174 related offline checks passed; four Luna requests, no desktop input or full-flow acceptance. Custom profiles/running hosts do not change automatically; reconnect to load. Installers are unchanged.

| 请求 / Request | 提交尺寸 / Sent | 回映点 / Original point | HTTP ms | Input tokens |
|---|---|---|---|---|
| 原尺寸基线 / Original baseline |2560×1400|(1008,49)|6097.538|3760|
| 显式缩图 / Explicit resize |1600×875|(1224,60)|5336.868|2590|
| 默认配置复测 / Default profile |1600×875|(1225,59)|5498.331|2588|
| 右侧小按钮 / Right-side button |1600×875|(2446,180)|4220.869|2592|

- Failure / 失败：原图上传再次复现小尺度bbox(62,36,1891,27)，即使模型声明image_size为2560×1400；不是下游显示框独自偏移。
- Root invariant / 根合同：声明原尺寸不证明几何实际采用原图尺度。控制唯一实验变量为提交尺寸后，地址栏bbox回映为(75,43,2300,36)/(76,43,2299,34)，与可见原框约(76,44,2298,32)接近；服务端内部精确规则仍未直接观测。
- Fix location / 修复位置：只改维护Luna配置，复用 `external_grounding_api.py` 现有 `_prepare_api_image`→输出尺寸校验→`_restore_api_geometry`。不硬编码1.215、不加补偿点击、不增加模型次数。 / Only the maintained Luna profile changes; existing preprocessing/validation/restoration handles the mapping.
- Why not app-only / 通用性：所有使用该Luna profile的截图均限定最长边，保留比例与原图绑定；不依赖地址栏/特定网站坐标。其他服务商和自定义profile默认不变。
- Regression / 回归：新增真实上传PNG尺寸、prompt尺寸、回映结果、原图不变的横图/竖图/方图/小图测试。旧配置3failed1passed，新配置相关7文件174passed/2.92s；JUnit `coordinate-default-red.xml` / `coordinate-default-green.xml`。完整命令：`python -B -X utf8 -m pytest -q tests/test_external_grounding_api.py tests/test_vision_grounding_contract.py tests/test_agent_grounding_target.py tests/test_capture_observation_geometry.py tests/test_execution_client.py tests/test_decision_candidate_annotation.py tests/test_decision_candidate_annotation_integration.py`。
- Safety and limits / 安全与限制：四次Luna调用均对已授权保存截图、零Decision调用/桌面输入/自动重试。阈值和门禁不变；原点仍在宽地址栏内，未证明所有Decision拒绝已消除。缩图有细节损失；小按钮点图人工视觉核对命中，不等同于真实点击验收。

原始请求context、模型JSON、回映候选、用量和时间已保存在 `.superpowers/sdd/2026-10-11-visual-execution-decision-flow/coordinate-api-evidence/`；`summary.json`汇总四次请求，`*-point.png`由项目维护标点器生成。旧profile另存 `luna-profile-before-coordinate-fix.json`；此前离线审计改读该冻结配置以保持可复现。 / Raw request context, model JSON, restored candidates and timing remain in the bounded API evidence folder; the prior audit now reads the frozen baseline profile.


## 2026-10-12 本地模型坐标检查 / Local-model coordinate check

本地 VISTA 默认执行路径未发现与 Luna 相同的尺度误映射。当前 direct_visual 默认不在客户端缩图（max_edge=0），模型原生输出 normalized_0_1000；显式缩图/裁剪按实际尺寸和原点回映。80项相关离线测试通过（2.19s），没有启动本地模型、调用API或操作桌面，未证明真实模型定位准确率。另复现非默认坐标标签隐患：worker可把同一[500,500]仅重标为normalized_0_1或roi_local_point而不换算；当前普通direct prompt返回normalized_0_1000，此隐患不能作为此前默认定位偏移的根因。 / No Luna-like scale mismatch was found in the default local VISTA route. Direct execution defaults to no client resize and native normalized_0_1000 output; explicit resizes/crops restore actual geometry.80 offline checks passed in2.19s, without model startup, API calls or desktop actions. Real grounding accuracy remains untested. A separate non-default labeling defect was reproduced: the worker relabels unchanged [500,500] as normalized_0_1 or roi_local_point. The normal direct prompt retains normalized_0_1000; this is not evidence of the earlier default-path failure.

源码 / Source: `app/api/vision.py:1463,1620,1663,1831,2138,8756`; `app/vision/local_provider.py:677,1012,1027`; `app/vision/model_workers/vista_openai_server.py:157,188,211`; local model README confirms native 0–1000 coordinates. The generic local region provider has its own explicit resize/remap and is not an extra transform in the VISTA point route.

命令 / Command: `python -B -X utf8 -m pytest -q tests/test_execution_direct_visual.py tests/test_selection_control_roi_context.py tests/test_small_text_field_roi.py tests/test_wide_form_control_roi.py tests/test_bound_button_accessible_name.py tests/test_capture_observation_geometry.py --junitxml=.superpowers/sdd/2026-10-11-visual-execution-decision-flow/local-coordinate-check.xml`.80 passed,0 failed; endpoint/model responses and screenshot backend are mocked. This verifies geometry and rejection contracts, not live Windows DPI or GPU inference. A separate pure-function call reproduced the label-only behavior and confirmed the current direct prompt uses normalized_0_1000.

本轮仅更新检查记录；未修改本地模型实现、默认配置、门禁或安装包。不将Luna的1600最长边设置直接套用到本地模型。 / This turn changes audit records only, not local implementation/configuration, gates or packages. Luna’s1600-edge setting was not copied to the local model.


## 2026-10-12 目标优先及旧规则清理 / Target focus and legacy-rule cleanup

2026-10-12未发布源码：目标优先规则已进入真实派发，输入前拒绝的绑定证明已补齐，已尝试输入和旧unknown不会被误记为未输入。修复现场发现的capture_id缺失、原生未解析字段误报不可写及ROI OCR冷启动缺口。Main分批回归166/78/180项通过（有重叠，不累计）。三次新浏览器实测都点击了地址栏，但均未输入网址；前两次代码故障已修，第三次Decision焦点条件0.54、visible_error0.21，返回review_required。因此Google→java→首结果未通过，不能宣称速度或准确率收益。三个宿主和自建窗口已清理。 / Unreleased source,2026-10-12: target-focused review now reaches real dispatch, and bound pre-input refusal proofs preserve the distinction from attempted/unknown input. Fixed missing capture normalization, unresolved-native-control misclassification and cold ROI OCR initialization. Main suites166/78/180 passed with overlapping coverage. Three new browser attempts clicked the address bar but never typed; the first two code failures were repaired, while the third focus Decision returned review_required (condition0.54, visible_error0.21). The Google/java/first-result flow remains incomplete, with no speed or accuracy claim. All three hosts and owned windows were cleaned up.

首次失败、同图对照、末端有界规则、旧全框popup拒绝和清理记录见[独立审查证据](TARGET_FOCUSED_DECISION_RULE_AUDIT_20261012.md)。旧记录不重写为成功。 / The linked audit preserves failures, API comparisons, bounded freshness, the full-box popup block and cleanup; historical outcomes are not rewritten.
