# Luna 动作后等待对比 / Post-action grace comparison

## 范围 / Scope

用户active goal授权低风险真实桌面/API测试。目标是减少普通执行固定等待，同时保留Luna实时定位、原输入门禁及Decision阈值。使用维护JSONL调用方和同一MCP会话，不使用Codex原生Computer Use。 / The active goal authorizes real low-risk desktop/API testing. Reduce ordinary-execution fixed waits while retaining fresh Luna grounding, existing input gates and Decision thresholds in the maintained persistent CLI/MCP session.

真实流程为Python官方文档首页→Library Reference→Quick search填写Built-in Types并提交→打开精确Built-in Types结果。A为render_grace_ms=2000，B为500；动作、条件、允许状态和加载声明相同，计划按ABBA顺序比较，避免把所有快速组都放在缓存更热的后半段。每轮以新request_id发起独立任务，所有既有任务须终态；不重放未知请求。 / The real task opens Python documentation, follows Library Reference, searches Built-in Types, and opens the exact result. A and B differ only in grace duration. ABBA ordering partly controls ordering/cache effects; each is a distinct requested trial after prior terminal completion, never a retry of unknown input.

主要时间取调用方发送至返回的UTC毫秒差，包含运行时等待但不含本轮计划准备、启动、人工看图和清理；同时保存服务端单调时钟分段。结果、Main介入、额外观察、模型请求数和清理分别记录，不用两组小样本宣称通用准确率。 / Primary wall time is CLI send-to-reply using UTC milliseconds, including runtime waiting but excluding plan preparation, startup, manual inspection and cleanup. Server monotonic segments, outcomes, Main reviews, observations, call counts and cleanup are recorded separately. Small samples cannot establish general accuracy.

## 首次基线与新缺陷 / First baseline and newly exposed defect

D:/AgentReviewAcceptance/luna-latency-20261011-01中四步均Decision确认、completed，send→reply为29.236秒，4次Luna/4次Decision。页面原图确为Built-in Types。公开images建议的instant_image(child_request_id, after)却报image_frame_unavailable，不能算完整证据交付验收通过。窗口owned-close成功、cleanup_verified=true、CLI退出0。 / The initial four-step baseline completed in29.236s with four grounding and four Decision calls. The original frame shows the correct page, but following the public image reference failed, so evidence delivery did not pass. Owned-window and host cleanup completed normally.

- Failure：任务已完成，但公开原图入口无法返回最后一步证据。 / Completed action evidence unavailable through the public image tool.
- Root invariant：child响应保留agent_command.v1接收快照和外层not_requested占位；图像入口未沿原ID解析终态agent-command并正确提取原after。 / The image resolver does not resolve the child terminal receipt and nested after-frame capture.
- Fix location：共用InstantSession.image，复用已有只读receipt_adapter；不新增截图或执行器、不修改旧回执。 / Repair the shared image resolver using the existing read-only receipt adapter, without recapture, new executors or rewriting receipts.
- Why not app-only：所有视觉代理动作和组合输入的原图读取都依赖同一入口。 / The common entry serves visual agent actions and compound input evidence.
- Regression：图像入口新增25项回归，加既有13项得到38 passed；Main六模块191 passed但stderr仍有COM异常，不能称干净通过。8张历史before/after原图只读回放均返回匹配SHA；第二现场的最终after及拒绝前before通过公开入口返回。 / Twenty-five new and thirteen existing image tests passed. The six-module Main run reported191 passed but retained COM diagnostics; it is not a clean acceptance. Eight historical original frames and live public after/before image delivery matched their stored hashes.
- Safety：保留原request_id、before/after角色、会话目录、PNG格式和SHA检查；缺失或篡改继续明确拒绝，不允许用新图冒原图。 / Retain request identity, temporal roles, session bounds, PNG and SHA checks; missing or corrupted evidence remains an explicit refusal.

首次调用方观察器ready事件记录遇到Node环境不提供process的诊断错误，未触发输入；已改用Date.now，错误留在caller-timing.json。计时起点在修正后的首次计划发送，不把观察器初始化问题算为产品故障或模型时延。 / An observer-only ready timestamp failed because the Node environment did not expose process. This was corrected before the first timed plan, using Date.now; the diagnostic is retained separately from product or model latency.

## 审核上下文只读探针 / Read-only review-context probe

D:/AgentReviewAcceptance/decision-context-20261011-01保留同一历史搜索图的两次判断。原声明needs_agent_review=.04；显式声明非模态且不遮挡目标、不需新增动作的登录提示为0。旧现场值为.28，模型未给出原因，因此不能唯一归因为登录提示，也不能据此承诺降低误判率。探针仅分析历史图像，不被任何运行中的动作采用；生产阈值与prompt未改，不允许重复同图判断直至得到通过。 / Two historical-frame judgments returned .04 under the original context and zero with a bounded nonblocking-state declaration, compared with the old live .28. The probability-only result does not establish causation or classification accuracy. These advisory probes authorize no action; production prompts and thresholds remain unchanged, and live callers must not repeat unchanged evidence to obtain a pass.

## 第二批中止的AB对比 / Aborted second comparison

证据根D:/AgentReviewAcceptance/luna-latency-20261011-02。A1(2000ms)四步completed，32.680秒；B1(500ms)前三步成功、第四步输入前拒绝，22.927秒，**不是成功提速结果**。Luna图仍显示Searching..，输入前图已显示Search Results及Search finished，精确链接向下移动41px。比较区域变化2159/4284(50.397%)超过2%门禁；action_executed=false、phase=not_dispatched。门禁正确阻止过期坐标点击。 / A1 completed in32.680s. B1 stopped before its fourth input in22.927s; it is not a successful speed result. Search completion shifted the target41px, and the unchanged freshness gate correctly refused stale coordinates.

根因：调用者把“已有结果”写成完成条件，又声明完成排除加载，但截图仍显示Searching；Decision返回condition_met=1/still_progressing=0。下一组须在两侧共同要求Search finished并排除Searching/Loading，再作独立比较。不能放宽定位门禁，也不能把修正条件后的复测改记为首轮通过。 / The caller declared visible results to be completed while search remained active. Both sides of a new comparison must require explicit finished state and exclude active progress; retain the first failure and the original freshness gate.

本批测试入口曾使用含大写字母的request_id，被客户端接收前拒绝；观察器未识别无ID的error而等待约60秒。这是测试调用方错误，不计入已接收任务或API时延。已改用小写ID及发送后事件索引等待。窗口正常关闭、cleanup_verified=true、CLI退出0且stderr为空。 / An uppercase test request ID was rejected before admission; an observer waiting bug added an unrelated delay. Subsequent IDs are lowercase and waits inspect new error events. Owned window and host cleanup succeeded with exit0 and empty stderr.

## 纯证据读取的依赖缺陷 / Evidence-reader dependency defect

Main组合测试发现原图读取会沿manual_observation→observation→capture→memory_observation→screenshot→window_manager导入pywinauto/comtypes，包含AnyIO线程初始化。生产只读路径不应加载桌面COM。已安排提取纯reference/read_ref模块并保持原有证据绑定校验；具体COM释放时序仍未证明，不以禁用测试或stub掩盖。 / Read-only evidence delivery unexpectedly imported the desktop COM capture stack through reference helpers. Extract pure reference helpers while preserving bindings. The exact native release sequence remains unproved; do not hide the issue by stubbing production imports.

## 依赖与提示修复验证 / Dependency and prompt verification

原图入口新增25例及既有13例通过；随后真实v3审核包读取揭示纯证据函数间接导入桌面COM。已抽出task_plan_observation_evidence.py，7个搬迁函数AST保持一致（仅_read_ref标识重命名），原模块兼容导出、真实采集静态依赖保留。Main最终7模块197 passed/8.61s、exit0、stderr为空；6项新subprocess回归对真实验证路径断言零native导入。此前191通过伴随COM诊断的结果保留，不改记。 / Extracted seven unchanged pure evidence helpers with compatible aliases. Main final seven-module run passed197 tests with clean stderr, including six real-validation subprocess cases prohibiting native imports. Preserve the prior noisy result.

Decision在completion_excludes_loading=True时新增明确排除部分加载内容的完成约束；Main provider/adaptive组合120 passed/1.49s、stderr为空。首轮119通过/1失败来自旧测试wrapper不接收include_upload关键字，恢复修改前provider也失败；仅修wrapper透传，生产预算逻辑未动。离线合同通过不等于模型判定质量提高。 / The provider now expresses the declared exclusion directly. Main passed120 provider/policy tests. One earlier failure was a stale test wrapper signature, independently reproduced before the prompt change; production budget logic was unchanged. Passing request contracts does not establish model accuracy.

## 第三批真实连续任务 / Third live batch

证据根D:/AgentReviewAcceptance/luna-latency-20261011-03。同窗口运行严格相同完成条件的A1和B1，均四步完成，但各2次Main审核，因此中止剩余BA，不声称完成ABBA或自动化性能验收。A1主页完成概率.47，搜索完成观察.86；B1标准库完成.23，Searching负例完成0/加载.16。所有灰区均停在原票据，无重试抽通过或重放输入。 / Both four-step trials completed with two Main reviews each; the remaining BA trials were stopped. Do not claim a completed ABBA or autonomous-performance acceptance. Preserve gray judgments and original-ticket recovery.

| 测量 / Measurement | A1 2000ms | B1 500ms |
|---|---:|---:|
| 包含Main及调用方间隔的任务总时长 / End-to-end including Main/caller gaps |144.358s|134.313s|
| CLI命令send→reply合计 / Sum of command send-to-reply segments |34.092s|26.618s|
| Main审核、原图读取及调用方间隔 / Main review, image retrieval and caller gaps |110.266s|107.695s|
| Luna HTTP / 4 calls each |13.740s|13.969s|
| Decision HTTP / request count |2.094s / 5|1.981s / 4|
| Main reviews |2|2|

各HTTP计时包含于命令段，不能再相加得到总时间。总时间不含启动、计划准备与清理。命令段差异也包括观察轮次/API波动，不能把差值全归因于等待缩短；这两个样本不证明通用收益。 / HTTP intervals are contained within command segments. End-to-end excludes startup, plan preparation and cleanup. Different observations and provider variance prevent attributing the entire difference to grace duration.

B1原after仍为Searching，Main通过维护observe补一张完成新图，再按v3审核包验证原动作并继续，未再次调用Decision。公开instant_result(images=after)返回标记为observation的原PNG及正确SHA；最终原动作after也交付成功。两个任务最终页面均正确；窗口owned-close成功、cleanup_verified=true、CLI退出0、stderr空，10项冻结源码哈希到清理后不变。 / B1 recovered via one explicit read-only observation, authenticated v3 review and original continuation, without rejudgment. Public original and observation image delivery succeeded. Final pages and maintained cleanup were verified, with clean stderr and unchanged frozen source hashes.

后续先用预注册正负例对比判断提示，不直接改默认等待或放宽阈值。 / Next compare preregistered labeled frames before changing the default grace or thresholds.

## 拒绝加载排除提示候选 / Rejected provider-prompt candidate

12次预注册shadow诊断逐一核对原件：主页完成legacy=.99/current=.47/concise=.64；标准库完成1/.23/.10；搜索未完成.01/0/0；搜索完成1/.99/1。前两张明确正例退化，简短并列改写也没有解决；因此撤回新增6行provider提示及相应6项文本测试，保留预算测试wrapper修复。provider恢复SHA2701e4291e0d6de1af70d749334dc1ec9002a6bedf58a70a9fe400591ba62640。Main撤回后114 passed/1.48s、stderr空；当前保留修复的验证为图像/证据197项加判断114项。 / A preregistered12-request diagnostic reproduced clear positive-case regressions in both candidate phrasings. The six-line provider patch and its six text tests were rolled back; the unrelated fixture repair remains. Main passed114 restored-provider tests with clean stderr, alongside197 evidence tests.

证据D:/AgentReviewAcceptance/decision-loading-prompt-20261011-01，preregister SHA639ac0e51ae784ed2a64be6407713d28cef98ab3ad01e12402a41e2522bc343a；12次均validated、adopted=false、零重试。HTTP合计3.729s，诊断wall3.941s，35232 input/total tokens，output0。只用于拒绝本次候选，不估算泛化准确率，不给任何动作授权。 / All12 advisory calls authenticated and remained unadopted, with no retries. These selected diagnostic cases reject the candidate; they do not estimate general accuracy or authorize input.

Searching负例的still_progressing在三种提示下均.16，说明本轮修改完成问题没有修复加载误判；还须核对加载描述与模型判读。下一探针只比较原加载图与完成图，使用搜索表单下的明确状态标题；结果另记。 / The loading predicate remained .16 under all three completion variants. Diagnose its separate visible-state declaration rather than infer progress from generic temporal wording.


## 可见状态校准与最终同会话验证 / Visible-state calibration and final session

调用方探针先登记两张固定原图，不修改生产provider：完成条件明确要求结果区出现“Search finished”和“Built-in Types”；加载条件只看搜索框下状态标题“Searching”。两次shadow分别得到completion/progress=0/1、1/0，均validated且adopted=false、无重试。HTTP总897.3602ms、wall937.447ms、5562 input/total tokens、output0。证据D:/AgentReviewAcceptance/decision-loading-caller-20261011-01；仅证明这两个样本可区分，不估计泛化准确率。 / Two preregistered advisory images separated the explicit Searching and Search finished states. Both calls authenticated without adoption or retries; no provider patch or general accuracy claim follows.

最终冻结原provider及9项相关源码，在D:/AgentReviewAcceptance/luna-final-20261011-01使用同一Luna/MCP会话顺序执行原视频任务及文档任务。 / Ten source files were frozen; the original video task and a real documentation task ran sequentially in one persistent session.

| 项目 / Measurement | Google→Bilibili→二次元→首个视频 / Video | Python文档→标准库→搜索→精确结果 / Docs |
|---|---:|---:|
| 步骤成功 / Successful steps |5/5|4/4|
| Decision自动确认 / Automatically approved steps |4|4|
| Main审核 / Main reviews |1|0|
| 首次start发送至返回 / Initial start send-to-reply |42.467s (review required)|26.196s (completed)|
| 含Main及调用方间隔的任务闭合 / End-to-end settlement |254.416s|26.196s|
| CLI命令段合计 / Command segments |42.825s|26.196s|
| Main/调用方间隔 / Main and caller gaps |211.591s|0|
| Luna HTTP / Calls |18.307s / 5|13.362s / 4|
| Decision HTTP / Calls |2.450s / 6|1.990s / 5|

视频原after为黑屏及骨架；第一次追加观察已有暂停按钮和00:01/2:09:56，第二张出现不同动画场景及浏览器音频标志。Main逐张核对这三张绑定原图后审核原票据并continue，没有重放点击。Decision在“visibly playing”的最新判断上refusal，不能把42.467秒称为全自动任务闭合，也不能把主会话/看图/工具间隔全算成模型推理耗时。 / Playback was evidenced by successive animation frames, a pause control and elapsed position. Main reviewed the bound captures and continued the original ticket. The temporal predicate was refused, so the initial return is not autonomous settlement; Main/caller gaps are not pure model reasoning latency.

文档任务仅在本计划显式采用500ms。首次搜索Decision为completion=0/progress=1，运行时有界观察后再判断为1/0并自动点击精确结果，无Main接手或输入重放。公开instant_image返回原after，SHA bf5dbae034dd6bd5529ec39e8fa6c090dbc25daea711bf4212fe79364135a6ee；Main查看确为Built-in Types页面。 / The explicit500ms documentation plan observed unfinished search, waited within its bound and adopted a new positive assessment before clicking the exact result. The public original image matched its SHA and showed the intended page.

owned-close返回window_closed；宿主cleanup_verified=true、CLI exit0、stderr空，10项源码到清理后哈希完全一致。caller-events.json、caller-timing.json、timing-summary.json、source-freeze.json及source-after.json保存原件。启动请求至返回5.730秒（含CLI就绪），select0.228秒；它们及计划准备、最终清理不含在上表任务计时。文档完成后的原图14ms返回，但观察器使用无匹配ID的等待多花10秒；此诊断间隔单列保留，无额外截图、API或输入，不计入文档完成时间。 / Maintained window/host cleanup succeeded with exit0, clean stderr and unchanged source. Startup, preparation and cleanup remain outside task timings. A post-task observer waited ten seconds for an unmatched image request ID despite a14ms response; this affected only diagnostic retrieval and is retained separately.

本次是两个真实流程的源码验证，不能当作完整ABBA、通用准确率或500ms默认推广依据。默认2000ms、判断阈值和动作门禁未改；未打包、安装、提交或发布。后续重点是播放等时间性条件的模型证据与接管耗时，再做同条件连续验收和冻结安装交付。 / These source-level cases do not establish a controlled speedup, general accuracy, or a safe universal500ms default. Defaults, thresholds and gates remain unchanged. Temporal evidence and takeover latency precede broader continuous and installed acceptance.


收尾只读复核未发现本轮图像解析及证据提取的实质问题；Main另实际运行源码收集，通用清单1195项、执行组件源码534项/资源32项均包含新纯证据模块。此检查不运行输入，也不替代真实安装包隔离预检；本轮无完整构建。 / Final scoped read-only review found no actionable defect. Main verified the new pure module is included in both maintained source collectors (1195 general entries;534 execution sources and32 resources). This is source collection, not an isolated installed-payload test.
