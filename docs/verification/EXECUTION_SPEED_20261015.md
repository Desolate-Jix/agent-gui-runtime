# Execution pipeline optimization / 执行流程提速

2026-10-15（Pacific/Auckland），未发布源码。用户最新顺序：先完成流程优化，再做多样本Decision benchmark。 / Unreleased source; pipeline optimization precedes the larger benchmark.

## First live attempt / 首轮真实结果

**完整流程失败，不能记为提速通过。** 计划为同窗口连续两轮Google→java→第一个普通结果；第一轮在地址栏阶段终止，第二轮没有执行。 / The first round failed at the address-bar stage; the second round was never dispatched.

- 窗口就绪至计划接收：服务端原回执UTC差 **201毫秒**，此前40.807秒。driver最初记录0.0毫秒受Windows/Python3.11 `monotonic`分辨率影响，不以该数值宣传零延迟；后续改用高精度计时。 / Server receipts prove a201ms launch-to-plan gap, down from40.807s. The initial driver0.0ms is not an exact latency measurement.
- 第一轮至失败约27.187秒；这是失败前耗时，不能与此前53.544秒完整成功任务直接比较。 / The27.187s failure latency is not comparable with the earlier complete successful plan.
- 第一次目标审核：Decision拒绝，普通Luna通过；URL随后确实输入。字段内容核验通过。 / Initial target review was corrected by ordinary Luna, and URL typing/value verification completed.
- 重新锚定地址栏并按Enter前，两层都判condition_not_met，故未再点击、未按Enter。 / Both stages rejected the later reanchor checkpoint; neither reanchor click nor Enter was dispatched.
- 即时generic诊断已实际记录 `deferred_to_settled_observation`，并有真实最终后图，不代表整个任务成功。 / The diagnostic consolidation was exercised, with a real settled after image.
- 后续通过同一client控制文件正常关闭本轮owned窗口，再finish；`window_closed=true`、`cleanup_verified=true`、进程退出0。原profile保留，无缓存清理。 / The owned window and host closed normally; browser data was retained.

Evidence: `D:/AgentGUI-Projects/evidence/execution-speed-20261015-01`。

3次primary、2次ordinary、1次定位均有返回，已知6,730输入＋414输出＝**7,144 token**，未知用量0；统一预算账本已结算，无剩余预留，余额4,992,856/5,000,000。709项冻结源码摘要均一致。 / All six API requests have known usage and the batch reservation was settled; source hashes match.

## Failure inspection / 失败检查

实际原图中地址栏框为 `(75,43,2261,34)`，点击点 `(326,59)` 在框内。派生mapping证明坐标换算一致；但为保留整个长框，Detail从2357×492缩至768×160，地址栏高度仅 **11.057像素**，而标记环直径22像素。 / The point maps correctly, but the wide field becomes only11.057px high in the detail panel, smaller than the marker diameter.

`rejected-candidate-view.png`与`rejected-candidate-mapping.json`保留该真实送审图和映射重建。它证明视觉细节被压缩，尚不能单独证明误拒的全部成因。 / The retained reconstruction proves loss of visual detail, not a complete causal attribution of model rejection.

后续修复限定为输入框目标的点击点局部Detail；完整Overview、原点/框/目标、问题、选项、阈值、两级审核与独立的完整字段值图保持。先离线核对映射及两层同图，再换一个新搜索流程验证。不得把首败重记为首次成功。 / The proposed repair changes only the field-target detail crop, followed by offline contracts and a fresh search flow. Preserve the initial failure separately.

## Offline evidence / 离线证据

Main运行scope、local observation、post-action transition、local policy、compound input、visual submit、instant MCP、window race、desktop discovery九组：**241 passed in17.30s**。Main外部driver检查：**13 passed in1.38s**。窗口相关worker窄组161passed；只有Main实际跑过的241项计入Main检查，不重复合计为独立样本。 / Main verification and worker checks are reported separately.

## Field detail repair and next live flow / 细节修复与新流程

输入框候选改为点击点中心最多384×160原像素、最多2倍放大，完整Overview保留。首败原图恢复为768×320 Detail、整体768×718，框高11.057→68像素；坐标、原目标、问题、选项、阈值不变。映射及认证版本隔离旧账本。Main新增13组相关检查 **245 passed in9.47s**；另101项worker窄检查含6个legacy/graphic/value完整wire SHA冻结，计数不重复合计。 / The field-only detail repair preserves original targeting and decision rules. Main's245 related checks pass; worker evidence is reported separately.

新流程证据：`D:/AgentGUI-Projects/evidence/execution-speed-20261015-02`，709项冻结源码摘要全部一致，原独立Edge资料目录继续保留。

- 第一轮Google→搜索 `python pathlib`→第一个普通结果Python文档，三步自动完成，无Main接管，driver耗时 **44.908秒**。Main已查看最终真实截图，URL为`https://docs.python.org/3/library/pathlib.html`。 / The first round completed automatically and the final source screenshot was inspected.
- 同窗口第二轮自动启动，地址栏输入与跳转成功；搜索框输入前Decision与普通Luna均返回 `condition_not_met`，输入零派发，交原Main审核。该轮21.413秒为到暂停的耗时，不是成功任务用时。 / Round two reached a real model rejection before typing; its time to pause is not a successful task latency.
- 本轮 `action_review_not_adoptable` 是非通过结果的统一包装；原两层结果均completed/nonpass，尚未进入service认证采用检查，并非ordinary通过后被新recipe误拒。 / The wrapper denotes a nonpassing assessment here, not evidence of an authentication mismatch.
- Main只读核查后取消原run，再关闭本轮owned窗口与宿主；`window_closed=true`、`cleanup_verified=true`、退出0，不重发失败动作，不删除缓存。 / Original-run cancellation and normal cleanup completed without input replay or browser-data deletion.
- 同一服务端边界：窗口启动完成12:22:50.716551UTC，计划接收12:22:50.877550UTC，间隔 **160.999毫秒**；第一批为201毫秒，此前为40.807秒。driver另测窗口就绪至首次client调用6.132毫秒，边界不同，不相互替代。 / The second server launch-to-plan gap is160.999ms; driver-call timing has different boundaries.
- 15次primary、1次ordinary、5次定位均有已知用量：43,579输入＋2,045输出＝ **45,624 token**，未知0。两批累计 **52,768/5,000,000 token**，无未结算预留。 / All21 requests have known usage; the unified objective journal is settled.

新旧搜索词、目标网站及模型返回不同，44.908秒不能与旧Java53.544秒宣称受控提速比例。第一轮成功不抵消第二轮失败，连续稳定性仍未通过。 / Different tasks and model outcomes prevent a controlled speedup claim; one pass does not replace continuous acceptance.

## Redundant encoding repair / 重复编码修复

候选准备阶段改为metadata-only，完整像素解码仍在派发账本前；current Choice直接生成原composite，只有legacy/predicate/freshness需要整窗标注时才延迟编码，旧帧格式仍兼容。Main17文件 **333 passed in9.14s**，含8条完整实际HTTP body摘要与4条eager/lazy字节对比；Sol只读源码复核未发现新增阻碍。未改问题、选项、坐标、阈值或API次数。一个原先禁止问题中出现任何focus字样的旧断言改为检查“焦点不在核验范围、选项只核对点击位置”，生产问题与冻结wire未变。 / Lazy candidate annotation preserves complete source validation and model requests. Main verification and a narrow source review passed; a stale lexical assertion now checks the actual no-focus requirement.

worker在同一真实原图上预热后各5次采样中位数：prepare223.818→63.866毫秒，prepare＋provider323.096→163.692毫秒；这是本地CPU处理，不是实际任务速度。原图、binding及HTTP body摘要一致。 / The same-image CPU measurement isolates local preparation work and is not an end-to-end speedup claim.

Main读取并审查独立复现脚本后，预热后交错5对复测：prepare223.293→63.528毫秒，prepare＋provider **321.571→163.301毫秒**，网络调用0。source稳定、原图/binding/完整HTTP body/上传图SHA均一致，也与worker原始记录吻合。原始记录和脚本在02目录`encoding-cpu/`，Main输出为`main-interleaved-recheck-01.json`。 / Main independently reproduced the local reduction with interleaved samples and matching frozen evidence; no real API or desktop was used.

首个新完整pathlib流程的分解保存在02目录`round1-breakdown.json`。44.908秒中，定位HTTP16.111秒、Decision HTTP5.285秒、其余23.512秒；固定等待与输入停顿7.710秒包含原三次跳转6秒。截图编码1.905秒已含在截图包络中，不重复加总；未细分余量5.404秒。 / The successful round's decomposition records nonoverlapping intervals and explicitly retains unknown local overhead.

## Frozen encoding candidate live attempt / 编码修复冻结候选实测

证据：`D:/AgentGUI-Projects/evidence/execution-speed-20261015-03`。新Google→搜索`sqlite transactions`→首普通结果计划，第一步地址栏输入前两层均completed/condition_not_met，零动作派发，第二轮未启动。17.530秒为至审核暂停，不能记为完成耗时。Main查看送审重建图：点`(480,60)`位于源地址栏框`(76,43,2257,36)`内，保留为视觉误拒诊断样本，不通过调阈值或Main强制放行。 / Both model layers rejected before the first input; no failed action was replayed. The marked source point appears inside the address field, retained for diagnosis.

原run取消、owned窗口关闭、宿主退出均完成，cleanup=true，709项源码摘要一致，profile与缓存保留。服务端启动完成到计划接收234.007毫秒。1次primary＋1次ordinary＋1次定位，5,672输入＋436输出＝ **6,108 token**。三批累计 **58,876/5,000,000 token**，未知0、预留0。 / Cleanup and source hashes are verified; all three calls have known usage and the unified journal is settled.

以上为03候选检查点；最新04流程优先结果见下方。保留此前首败，不将新任务成功回写为旧任务首次成功。 / The preceding03 checkpoint remains historical; the04 pipeline-first result follows. Earlier first-attempt failures are not relabeled.

## Pipeline-first follow-up / 流程优先补充

用户再次明确先优化流程、benchmark随后。本轮保持问题、选项、阈值、Luna推理配置及Decision→普通Luna→Main不变，完成三片共享流程优化： / The latest steering prioritizes pipeline overhead while preserving model questions, thresholds and review routing.

- **Before image / 前图：** 默认实时委派视觉与Enter回锚用同次内部live capture作为报告前图；原PNG字节复制到每step目录并在派发前落盘，省去外层重复采图。内部pre-action、派发前fresh及最终settled图不删。仅正式resolver确认direct_visual且内部目标精确为AgentGroundingTarget/VisualSubmitTarget的原scope可用；无目标本地模型、学习/记忆、独立API、ROI与dry run保持原行为。
- **Pixels / 像素：** MSS原生BGRA直接解码RGB，不再逐通道切片建中间RGB缓冲。三个2560×1400历史原图预热后交错10对采样：原转换中位13.076/13.662/13.779毫秒，新6.248/7.019/7.076毫秒；像素及PNG字节与原图一致。脚本与原值在02目录`pixel-conversion-cpu/reproduce.py`和`main-interleaved-02.json`。这是孤立CPU测量，不是整轮提速比例。
- **Connections / 连接：** Decision与普通Luna共享原client，idle expiry从5秒改60秒；真实本机回环验证6/59秒闲置后复用、61秒后重建、close释放socket/线程。原HTTP截止、代理隔离、请求数量与零重试不变；未测量真实TLS节省。

默认入口修正符合共享合同：最初显式metadata夹具通过，但Main核对真实旧回执发现默认metadata为空，不能用raw声明判断内部路线。修复在共用资格函数中复用正式resolver，并读取已有内部target；新增默认入口RED2失败→GREEN，真实构造target、真实_post_action及目标适配器证明outer0/inner1/dispatch-scene fresh1。33项新增用例还覆盖签发SubmitTarget、公开source不能绕过、复制留存、落盘失败、取消、线程/请求/窗口不匹配与未知结果。 / A default-entry regression exposed a raw/effective configuration mismatch. The shared fix uses formal routing facts and existing internal targets rather than adding a public bypass.

Main最终26文件 **579 passed in58.42s**，包含截图、输入、回执、派发边界、两层复核与HTTP时限/关闭；UTF-8/AST及diff空白检查通过。有界只读源码复核未发现新增P1/P2，属于源码审阅，不是独立实机验收。调度审计也确认终态审核后已在同次advance排下一步，没有需要删除的额外200毫秒等待；完成通知的最多200毫秒发现延迟留作后续，不修改取消/公平性架构。 / Main's relevant checks passed. Narrow source review is distinct from independent desktop acceptance; an assumed post-review scheduler delay was disproved.

### Fresh continuous live check / 新流程连续实测

证据：`D:/AgentGUI-Projects/evidence/execution-speed-20261015-04`。完整计划在启动前准备，同一个MCP连接、同一owned Edge窗口、原保留profile，两轮首次执行Google地址输入→搜索`python json`→打开首个普通结果。 / The complete plan was prepared before launch and executed twice in one owned browser window and connection.

| Item / 项目 | Actual / 实际 |
| --- | --- |
| Round1 / 首轮 | 37.646643秒，3/3步完成 |
| Round2 / 第二轮 | 26.325417秒，3/3步完成 |
| Viewport / 视口 | 1264×892，两轮相同 |
| Target / 最终页 | `https://docs.python.org/3/library/json.html` |
| Main handoffs / Main接管 | 0 |
| Calls / 请求 | 定位6、Decision20、普通复核1；零自动重试 |
| Primary / 首层选择 | condition_met19、evidence_insufficient1；后者由普通Luna复核后继续 |
| Shared before images / 前图共享 | 10次全部命中，10份持久副本字节一致，少10次外层采图 |
| Cleanup / 收尾 | owned窗口正常关闭、宿主stop，cleanup=true；profile/缓存保留 |
| Source / 源码 | app/scripts共739项SHA前后匹配 |
| API usage / 用量 | 41,413输入＋2,308输出＝43,721 token |

Main逐图查看两轮Google首页、结果页以及最终Python文档；两张最终PNG摘要一致。全部36个历史evidence_refs的文件摘要核对通过。`audit.py`只读解密本会话DPAPI账本，按request_id去重定位调用，复核总usage已包含普通层，避免重复计费；`live-metrics.json`和`budget-after.json`保留汇总。四批目标API累计 **102,597/5,000,000 token**，未知0、预留0；benchmark付费请求0。 / Main inspected the actual images and verified all36 evidence references and739 source hashes. Usage includes the secondary request exactly once; the unified budget is settled.

这证明当前冻结源码的一个新浏览器流程可连续完成，不能证明通用准确率或长时间稳定。当前视口与查询不同于旧Java/pathlib基线，且缓存保留，不能把37.647/26.325秒解释为某片修复的受控净收益。当前候选尚未做真实中断、弹窗、重开、安装或独立Agent验收；取消/缺图等目前仅有离线覆盖。未构建、提交或发布，学习模式未纳入本轮发版范围。 / This is a limited two-round continuity check, not a general reliability or controlled speed benchmark. Adverse live cases, packaging and independent acceptance remain pending.

## Request-phase cancellation and same-session recovery / 请求阶段取消与同会话恢复

**Candidate06 / 候选06：** `D:/AgentGUI-Projects/evidence/execution-speed-20261015-06`。相对04只改四个公共取消处理源文件；739项app/scripts源码哈希冻结并在真实运行结束后核对。Main查看原始菜单、Google后图，并核对全部15条history证据摘要。 / Only four cancellation-handling source files changed from04;739 source hashes and15 history evidence references were verified after the live run. Main inspected both original after images.

1. **Failure / 失败：** 05在真实Luna定位请求期间取消。原HTTP迟返及3124 tokens已保存，派发列表为空，但组合输入把内部取消异常记成`result_unknown`，job的`action_executed=false`被污染为null。流程仍是`cancel_requested/verification_required`，120秒后验收暂停，菜单未执行。原关闭窗口请求被active-plan门禁拒绝；保留拒绝，正式stop后宿主正常清理，后续项目只读绑定确认旧窗口不可用，空闲测试观察器才结束。05完整失败记录没有改为通过。 / Candidate05 lost the known input fact at a compound exception boundary, leaving cancellation unsettled. Its failed acceptance, close refusal and subsequent normal host cleanup remain preserved.

2. **Root invariant / 共享合同：** 可信内部协作取消不能凭空引入未知副作用。原子派发账本才是False/True/None的依据；取消状态或异常文字都不能证明零输入。已发API的返回与用量仍须保存，不采用迟返坐标，不重放输入。 / Typed internal cancellation must preserve the atomic dispatch facts; neither a cancelled label nor an exception message proves zero input.

3. **Fix location / 修复位置：** `app/core/vision_admission_contract.py`增加共享`AgentCommandCancelled`类型，原Jobs私有取消继承它；`input_sequence.py`和`form_fill.py`各捕获层只透传该类型。Jobs终态合并、workflow/backend及原派发账本均未改；没有新增“所有cancelled都视为零输入”的规则。 / A shared typed signal crosses compound-input handlers without changing dispatch accounting or workflow settlement rules.

4. **Why common / 通用性：** 同一处理覆盖视觉输入、原生路线和form_fill中的text/date/checkbox，适用于浏览器与其他Windows软件。不是Google地址栏特判，也没有新增执行器。 / The fix covers the shared compound-input boundary rather than a site-specific action.

5. **Regression / 回归：** 初始主链RED1失败，表单扩展RED3失败；新增8项GREEN。真实grounder协议（阻塞MockTransport）→真实Jobs→组合输入→TaskPlanRuntime核对同ag迟返usage、无额外Decision/输入、取消history、清空pending及同会话新计划。反例覆盖已输入True前缀、派发开始后的None、同文案普通异常和伪公开False属性。Main扩大相关覆盖时首次450通过/1失败：旧截图替身缺少真实绑定元数据，提前在前图保存处失败而未到Decision取消点；只补齐夹具，原断言未改，窄项通过后整组 **451 passed in37.73s**。只读独立源码复核未发现新增P1/P2，另跑新文件8通过；这不是独立实机验收。 / The initial red cases and broader fixture failure are retained. Main's final affected group passed451 checks; source review is distinct from independent desktop acceptance.

6. **Safety / 安全影响：** 窗口身份、前图、坐标、新鲜度、Decision选择与原动作门禁不放宽。实际已输入或未知派发不会被清为False，普通未知异常仍保留未知，取消不会触发重放。 / Existing gates remain unchanged and prior or uncertain input effects remain recorded.

### Live06 result / 06真实复测

- 在同一个正式ExecutionClient/MCP连接、同一owned Edge窗口与保留的测试profile中：原定位请求期间取消，原job与plan均终态cancelled，`action_executed=false`、dispatch=[]、pending清空、history保留。实际HTTP正常返回并计入用量，没有宣称网络请求已被中断。 / Cancellation settled the original job and plan without input; the in-flight provider response was retained and accounted.
- 原会话新任务打开Edge“设置及其他”菜单，Decision核验菜单可见；下一步在地址栏连续点击／全选替换／Enter进入Google，菜单关闭。两步success，无Main接管、无自动重试；Main查看两张原始后图。 / A new task opened the real Edge menu and then navigated through the address bar; both steps completed automatically.
- 正式关闭owned窗口成功，原宿主phase=stopped、cleanup_verified=true、sampler_stopped=true、cleanup_errors=[]；原runner进程已退出。只保留测试资料，不清理浏览器缓存或用户资料。 / Owned window and host cleanup were verified without deleting browser data.
- API请求及token以同目录`api-usage-audit.json`和已结算预算为准；不能把宿主report中过期的Decision used=0当作未调用。实际账本需单独核对。 / The persisted dispatch ledger and audited usage take precedence over the stale zero counter in the final host summary.
- 本轮是取消缺陷修复后的同范围实测，05首败保留。普通三步两轮数据来自04；06不是新的完整三步两轮或安装包验收，不将不同任务／视口作受控提速比较。最终提示词／配置冻结后的完整候选、独立实机与安装包验收仍在发布前集中完成。 / This is scoped recovery regression, not a replacement for final frozen-candidate or installer acceptance.


| API06 / 类型 | Calls / 唯一调用 | Input tokens / 输入 | Output tokens / 输出 |
| --- | ---: | ---: | ---: |
| Grounding / 定位（含取消原请求） | 3 | 8315 | 1241 |
| Primary Decision / 主层 | 6 | 6951 | 0 |
| Ordinary Luna / 普通复核 | 0 | 0 | 0 |
| Total / 合计 | **9** | **15266** | **1241** |

06合计 **16,507 tokens**，其中取消原请求3,253；全部已知，主层六次均为condition_met，本轮没有触发复核或证明复核纠正效果。Main直接解密只读账本独立核对；JSON-only导出会遗漏一次523-token的输入值核验，宿主旧report的used=0也不作计量依据。包含05失败请求在内，目标预算已结算 **122,228 / 5,000,000 tokens**，reserved=0、未知=0、余额4,877,772；尚无benchmark付费请求。 / The06 run used16,507 tokens, including the cancelled call. All usage is known; six primary choices passed and no secondary review occurred. Main independently checked the actual ledger, including a field-value check absent from the JSON-only export. Total objective usage is122,228 tokens with no outstanding reservation or unknown usage.

**Next / 下一步：** 流程修复已收拢，保持问题、阈值、两层路由和版本号；benchmark随后按冻结数据与预算进行。先不构建、不推送、不发布。 / Pipeline changes are consolidated; benchmark evaluation follows before release preparation.

## 0.1.3 consolidated source candidate / 收拢源码候选

此前04/06属于历史检查点。随后完成冻结提示词评测、报告计数和文档载荷闭合，并修复改题后的旧回执误认证。执行版本进入未发布0.1.3，739项源码冻结摘要为`f43e352cffe60076ad217194324575bed23e73d022ed46c042fd5f0ec6e7acf2`；以下两次使用相同源码、原保留Edge profile及全新运行数据，均正常关闭本轮窗口/宿主。 / The following source runs use the same consolidated frozen0.1.3 candidate, retained browser profile and fresh runtime data. They do not rewrite the earlier checkpoints or imply publication.

| Run / 本轮 | Outcome / 结果 | Plan time / 计划耗时 | API use / 用量 |
| --- | --- | --- | --- |
| `execution-release-013-20261015-main-01` | Google→python datetime：首轮完成；第二轮输入正确但被两层误拒，未按Enter，**连续项失败** / First round completed; round two false-rejected entered text, no Enter | 37.180s；failed21.014s | 5grounding＋16primary＋2ordinary；34,557tokens |
| `execution-release-013-20261015-main-02` | DuckDuckGo→Python decimal documentation→首个普通结果，首次连续两轮完成 / Fresh task completed twice without Main | **31.476s；32.214s** | 6grounding＋20primary＋0ordinary；41,806tokens |

Main查看02两张最终原图，均为Python decimal文档；逐项核对history证据摘要、全部739源码及原始账本。02原窗口就绪到首次计划调用6.688ms，少10次外层重复采图，其持久副本与内层源PNG相同。宿主报告改为每次发布读取真实账本，01/02最终used分别18/20，包含普通复核计数；旧06的零计数记录不改写。不同任务、视口与模型响应存在差异，不能用这些数值宣称受控百分比提速。 / Main verified both final images, all evidence references, frozen sources and ledgers. The source02 caller submitted after6.688ms and removed10 duplicate outer captures while retaining identical durable PNGs. Refreshed report counters matched actual primary/secondary dispatches. Different tasks and model responses do not establish a controlled speedup.

### Retained false rejection / 保留误拒

01第二轮`search_datetime`输入后，预期与原图均为`python datetime`。Decision与普通Luna均选择`condition_not_met`；HTTP137.555ms/1517.256ms，服务总1710.842ms，合计976输入＋7输出token。Main及Sol分别核对完整字段送图重建（1456×184）、外沿标记、坐标与摘要：文字完整，无灰补全或标记遮挡，原request digest与持久账本相同，两层问题/图片相同。重建是依据冻结源码和原绑定复原，**并非原HTTP捕获**。内部误判原因未知，未改阈值、绕过结果或反复请求该图；02成功不代表01误拒修复。 / The correctly entered value was falsely rejected by both models. Offline reconstruction found no missing text, annotation obstruction, mapping or expected-value mismatch. Reconstruction is not an original HTTP capture; the model's internal cause remains unknown. The second task's success does not repair or erase this failure.

此记录归类为输入值审核的模型误拒：没有已证实的应用专属程序修复；通用合同仍是结果未被可靠核验时不派发Enter。本轮回归保留该证据作后续独立诊断，不据此改写既有保留集。安全门禁未放松。 / This is a retained model false negative, with no evidenced site-specific code repair. The common contract withholds Enter when the value is not adopted; evidence is retained for future independent diagnosis without altering the frozen benchmark or relaxing gates.

### Prompt-result authentication repair / 问句结果认证修复

1. Failure / 失败：通用问句更新后，旧`decision_prompt.v2`账本仍可被认证为新问题结果。
2. Invariant / 通用合同：已采用结果必须绑定实际问题版本，不能只绑定相同截图与请求字段。
3. Fix / 位置：`app/judgment/service.py`为已改的candidate、recorded-click、compact text及page-result分支分别绑定prompt revision。
4. Common scope / 非站点补丁：公共服务覆盖所有相应桌面/网页请求，未变的predicate、native、identity、target_check、temporal及字段内容分支保持原摘要。
5. Regression / 回归：4类旧账本先RED；新增20项验证旧ID冲突零重派、新ID一次派发后回读零请求及16类未改分支兼容。Main大组963通过、5处转义/旧wire断言失败；仅修测试兼容后148项受影响检查通过，首失败日志保留，重叠测试不相加。
6. Safety / 安全：旧结果不能继续授权；冲突不自动追加付费，不改变问题、图片、模型、阈值或输入门禁。

原始证据目录位于`D:/AgentGUI-Projects/evidence/`下上述run名；冻结评测详见[benchmark报告](DECISION_PROMPT_BENCHMARK_20261015.md)。本检查点目标API累计**1,507,798/5,000,000tokens**，预留和未知均0。最终安装、取消恢复及独立验收仍待完成；当前仅准备发布，不上传。 / The objective ledger now totals1,507,798tokens with no outstanding reservation or unknown usage. Final packaging, cancellation/recovery and independent acceptance remain pending; this is release preparation only.


## Final installed candidate checkpoint / 最终安装候选检查点

This is a preparation checkpoint, not a release. / 本节为发布准备检查点，不代表已发布。

| Frozen installed Main / 冻结安装候选 | Actual / 实际 |
| --- | --- |
| Task / 流程 | DuckDuckGo → `Python decimal documentation` → first ordinary result / 首个普通结果，同会话两轮 |
| Plan wall time / 计划耗时 | **35.3881638s / 30.5629882s** |
| Ready to first submission / 就绪至首次提交 | 7.2317ms |
| Primary / grounding / ordinary / 请求数 | 20 / 6 / 0，两轮合计 |
| Tokens / 用量 | 39,182 input + 2,766 output = **41,948** |
| Evidence / 证据 | 572交付源码SHA与history引用核对；Main查看两张最终Python decimal原图 |
| Cleanup / 收尾 | owned窗口、宿主正常关闭，原测试profile和缓存保留 |

源码02为31.476／32.214秒、41,806tokens。两组任务相同但不是受控旧版对照；不能把两轮平均差异或提示词HTTP时间写成动作提速。共享观察减少10次外层采图；BGRA解码组件测量约13ms→6–7ms，像素与PNG字节不变，不等于完整动作每步节省该数值。 / The source pair took31.476s/32.214s and41,806tokens. These are not controlled comparisons with an older release. Ten outer captures were removed; decode timings are component measurements only.

### Adverse paths and evidence gap / 异常路径与证据缺口

- `execution-release-013-installed-adverse-01`：请求中取消原定位已认证为零输入，原job/run取消、dispatch空、pending清空。之后Edge菜单目标被Decision及普通Luna同时拒绝，没有点击，恢复项失败；Main查看原图，内部模型拒绝原因未知。共8,018tokens。原取消、正常关窗与finish全部保留。 / Cancellation passed, but both judges rejected the subsequent Edge menu target. Recovery failed without input; cleanup passed.
- `execution-release-013-installed-adverse-02`：原请求取消同样通过；新Bing菜单任务在Decision前的定位结果合同校验失败，`api_grounding_invalid`，零输入。HTTP envelope与usage已经读取；并非已证实的网络超时、Decision误拒或坐标缩放故障。 / Cancellation passed; the Bing recovery failed during grounding-result validation before Decision, without input. An HTTP response and usage were available.
- 该宿主创建grounder时`capture_trace=False`，Jobs仅保留provider/attempt，未持久化原`raw_model_text`与具体校验错误，现有证据无法判断究竟哪个字段、描述或geometry检查失败。不反复付费重放，也不猜测根因。 / The host disabled capture traces and persisted provider/attempt data only, so the raw model text and specific validation error cannot be recovered. The precise cause remains unknown; no paid replay or speculative fix was made.
- 两次异常run均取消原等待后正常关闭本轮窗口和宿主；退出码0仅证明驱动正常收尾，**不代表恢复测试通过**。独立桌面验收只有准备记录，未执行。 / Both failed runs were settled and cleaned up normally; a zero driver exit code is not recovery acceptance. Independent desktop acceptance has not run.

Failure / 失败：定位合同拒绝结果，阻止恢复流程。Invariant / 合同：不采用无效坐标，同时应持久化可诊断的原返回与校验错误。Location / 位置：公共external-grounding与Job证据边界，不是Bing专属适配。Why common / 通用性：所有采用该grounder的网页和Windows目标共享此边界。Regression / 回归：本轮只有保留真实失败证据，尚无根因修复及回归通过，不伪记闭合。Safety / 安全：未放宽门禁，没有采用无效结果或派发点击。 / The unresolved common-layer observability gap must be repaired and checked before retrying recovery; no safe-input contract was relaxed.

### Delivery and final accounting / 交付与最终计量

执行版号0.1.3。一次构建的payload为572个Python源码／58资源，632个最终文件；隔离入口与依赖检查通过，43项针对性包内离线检查通过。原源码52文件大组963通过／5旧断言失败／1 deselected；只修测试的旧golden和JSON转义比较后，相关148项通过，首败日志保留，重叠检查不相加。 / The isolated payload and43 targeted checks passed. Initial broad-run assertion failures and the148-check affected rerun are retained separately.

测试安装及原安装器正常卸载均通过，`integration_written=false`，最终无测试安装残留；浏览器资料、证据和候选安装器保留。首次卸载按保护规则保留6个运行时生成的空目录及归属文件，因此“零残留”检查失败；逐项核对无内容后仅移除空目录，再次调用原卸载器完成，首记录保留。安装器未签名，SHA-256 `d1939edd3f6339a48dde35c87830698a572c154ce8e680ea797976ea1d2179e7`。测试使用已有解释器，并非全新机器依赖安装证明。 / Installation and final uninstallation passed without integration writes. The first uninstall intentionally retained unknown empty runtime directories; its no-residue assertion failed. After verifying and removing only those empty directories, the original uninstaller removed its ownership files. Both records and the unsigned candidate are retained; this did not validate a fresh machine dependency setup.

本目标API累计 **1,564,031 / 5,000,000 tokens**，预留0、未知用量0，包含训练、验证、保留评测、二层调用及失败／取消请求；详见原统一追加账本。最终失败用量详见`execution-release-013-installed-adverse-02/api-usage-audit.json`。 / Final accounting includes all known successful, failed and cancelled requests, with no outstanding reservation or unknown usage.

发布简介位于本轮外部候选`RELEASE_NOTES.md`。冻结安装器内README是构建时检查点；源码README及外部简介记录后续验收，未静默重打包。**当前不发布：先补定位失败可诊断性并修／验恢复，再完成同一冻结候选的独立桌面验收。** 未提交、推送或上传；学习版不变。 / Post-build results live in source documentation and external notes; immutable package documents remain the build-time snapshot. Release acceptance remains incomplete.


## Post-restart primary failure diagnosis / 重启后主路径故障诊断

This source increment is newer than frozen candidate01; its old installer and measured flows remain unchanged. / 本源码增量晚于冻结candidate01，旧安装器和旧实测数据不变。

1. Failure / 失败：补齐诊断后，对原Bing菜单图只读请求一次，Luna返回`…92eb…`而本地请求为`…92ab…`，一个a抄成e，`grounding request_id does not match runtime request`。坐标约1195,113位于实际菜单图标；这是本次新复现的确证，不能倒推无原文的旧失败。
2. Invariant / 合同：请求与截图身份属于Runtime，本次HTTP调用的局部capture快照是依据；不得把长随机ID的文字复写当成视觉定位必要工作，也不得静默覆盖旧协议返回的错ID。
3. Fix / 位置：公共`external_grounding_api.py`新增显式runtime协议，模型schema/context去两ID，严拒回复带保留字段后本地绑定并完整验证；默认legacy序列化/wire不变。Jobs在原attempt同次写失败诊断；取消迟返保留原调用和用量。两个Luna维护示例启用新协议。
4. Common scope / 通用性：覆盖所有用此外部视觉API的网页/Windows目标；不是Bing坐标、网址或菜单文字特判，不新建执行器。
5. Regression / 回归：诊断初始6fail/1pass；JSON转义泄露、孤立surrogate和深嵌套JSON掩盖原error均先RED，再修复。6文件最终172passed；另外6文件交付/识别路由/MCP组186passed（101.25s）。维护示例换协议曾使四个旧缩放fixture失败，只适配模型回复字段并增加本地ID断言，原尺寸/边缘坐标/源PNG断言全部保留。覆盖保留字段正确/null仍拒、错尺寸/点/额外字段拒绝、并发不串、HTTP期间capture变更、原job取消与计量。独立只读复核提出的具体问题均通过相关回归关闭。
6. Safety / 安全：继续拒绝无效结果；未知用量不清零，失败不重试，不回退。新本地身份不授权动作，仍须新鲜截图、Decision和原执行门禁。持久化诊断对凭证、图片数据和异常Unicode显式脱敏/转义，默认成功回执形状不变。

| Historical-image API probe / 历史图诊断 | Original echo mode / 旧模式复现 | Explicit runtime mode / 新模式 |
| --- | ---: | ---: |
| Outcome / 结果 | ID typo rejected / ID抄错拒绝 | Valid grounding / 有效定位 |
| Input / 输入token | 2,792 | 2,705 |
| Output / 输出token | 329 | 413 |
| Total / 总token | 3,121 | 3,118 |
| HTTP elapsed / HTTP耗时 | 5228.563ms | 4910.591ms |
| Input dispatched / 输入派发 | 0 | 0 |

两次使用同一原图与目标，但每组仅一次；不能声称准确率提升、稳定延迟或动作提速。新模式返回点1195,114，Main查看原图确认命中Bing网页菜单；内部request/capture/SHA绑定核对通过。Decision保留benchmark、问题、阈值均未改。 / One request per protocol on the same recorded image cannot establish accuracy or latency gains. Main inspected the image and checked local provenance; no Decision benchmark retuning occurred.

原始证据在`execution-grounding-diagnostics-20261015-01`与`02`，包含result、绑定SHA、预算和legacy wire对照。API累计 **1,570,270/5,000,000tokens**，预留0、未知0。当前源代码尚未新的桌面连续/取消恢复、交付包或独立实机验收；不把历史图重放、旧candidate01的43项包检查或旧正常两轮冒充新源码验收。未提交、推送、发布或改学习版。 / Current source still needs fresh desktop and package acceptance; older frozen-candidate results do not transfer automatically.

## Current runtime-bound source live checkpoint / 当前本地绑定协议源码实测

Fresh-data same-session Bing→`Rust standard library collections documentation`→first ordinary result passed twice, **33.2182502s / 30.5493873s**. All six steps completed without Main handoff;20 primary,6 grounding,0 ordinary;38,880 input +2,293 output=**41,173 tokens**. Ten removed outer captures were checked against persistent inner PNGs;36 history refs and all739 source SHAs matched. Main inspected both final Rust `std::collections` images. Owned-window and host cleanup passed. / 新数据同会话两轮正常流程通过；完整原图、引用及739源码绑定核对通过，正常关窗与宿主收尾。不同任务不能作旧版受控提速比较。

In `execution-release-013-runtime-binding-adverse-01`, the original requesting-phase cancellation settled with zero input, one same-ID API call and known usage. Recovery localization and click succeeded; original after SHA`2ee8c96b321542913f6ecf70eb5cd488f5a98d63969aa5eab383c8072f9b0014` shows the Bing webpage menu open. Primary and ordinary Luna both returned`condition_not_met`, so the runtime exposed the Main review packet without repeating the click. Main inspected that original image, cancelled the original pending run, closed only its owned window and finished normally. **Automatic recovery did not complete; Main review→continue was not exercised in this batch.** / 请求中取消通过；菜单定位、点击及after采图成功，但两层均误拒，原证据包交Main且没有重复点击。Main核图后取消等待并正常收尾；不能把退出码0或收尾通过记成恢复通过。

The user now explicitly accepts Main as the backstop for these model mistakes. Perfect model judgment is not a release prerequisite; do not repeatedly tune prompts, relax thresholds or retry to erase this failure. The remaining relevant acceptance is authentic Main review with the supplied hashes, continuation without duplicating the completed action and final cleanup. This observation alone does not establish a universal model capability ceiling. / 用户最新确认由主Agent兜底模型误拒；后续验收重点为完整证据交接、Main认证审核后不重复原动作地继续和收尾，不为单个菜单刷通过。单次现象不能证明普遍能力上限。

Adverse usage:2 groundings,2 primary decisions,1 ordinary review;**9,340 input+668 output=10,008tokens**, including the cancelled late response;unknown0. Main checked the ledger/call totals before settling. Objective total is**1,621,451/5,000,000tokens**, reserved0. Frozen benchmark/thresholds, official0.1.2, learning release and retained browser data are unchanged. Source is newer than candidate01; candidate02 and independent installed acceptance are still pending. / 本批用量及取消迟返全部计入；旧候选不可冒充新源码验收，未提交、推送或发布。

## Main-assisted continuation on current source / 当前源码 Main 辅助续行

`execution-release-013-runtime-binding-handoff-01` used fresh data with the same739-source freeze and retained browser profile. Request-phase cancellation again settled with zero input. After the real Bing menu click, both judges returned`condition_not_met`; Main viewed original after SHA`88882fe60aed986abc14739d9f270169f595c768deb2f348092eda4a9e51f985` and verified all six original evidence refs. Main submitted the exact caller-controls review binding (original execution ID, after SHA, packet SHA, evidence-set SHA and assessment round), with success and a visual reason. The runtime projected a separate continue request. Main explicitly continued the original run; the next address-bar input navigated to Google, authenticated by Decision. Main inspected the final Google image. / 新数据真实验证原请求取消，以及模型误拒后Main核图、绑定原证据审核、显式续行原run、进入Google和最终截图；不跳过运行时review/continue合同。

The recovery history has exactly two rows: menu=`judged_by:agent`, navigation=`judged_by:decision`. The original menu job and its single dispatch were not repeated. Owned window and host closed normally; no browser data was cleared. **Main-assisted recovery passed; fully automatic model recovery did not pass.** Earlier failed/rejected runs remain unchanged. No production source, prompts, thresholds or frozen benchmark were changed; the observer added only formal same-run status/review/continue controls. / 恢复history两行分别为Main和Decision核验，原菜单仅1次派发；Main辅助恢复通过，不写成模型全自动恢复通过。源码/问句/阈值均未改，旧首败保留。

Main deliberation, tool observation and control submission time is included in this assisted journey; it is not a model-only latency or autonomous action-speed benchmark. Current source normal two-round timings remain33.218/30.549s. Candidate02 will be built once after source closure; installed and independent acceptance are still pending. / 接管过程包含Main看图与调度，不当作模型延迟或自动动作提速；仍须新包与独立验收。

## Candidate02 installed and independent closure / 候选02安装与独立验收闭合

Main installed Bing→Rust documentation two-round plan times were30.8092487s and27.3535762s,41,097 API tokens total;20primary/6grounding/0ordinary,10 removed outer captures. Main then passed request-phase zero-input cancellation and authentic evidence-bound Main review→explicit same-run continuation→Google→normal cleanup. / 安装态正常两轮及取消、Main辅助恢复通过；原菜单只点击一次，不写成模型自动恢复通过。

Sol independently used the same frozen candidate, a fresh data root and the retained test profile: cancellation, one Bing-menu review by the Main role, two consecutive Bing→Python itertools documentation journeys and cleanup all completed. All7 history rows passed; six post-menu steps were authenticated by Decision. Main checked the final two original Python documentation images and45 history references. Usage51,072tokens,unknown0; no independent model/prompt/threshold changes. / 独立同会话完整7步通过，含一次Main角色兜底；保留所有模型误拒，不以重跑覆盖首败。

Candidate02 has572 Python files+58 resources+2 generated manifests=632 payload files. Isolated real entrypoint/dependency validation and43 package contracts passed; source172 core and separate186 delivery/routing checks remain distinct. Installer SHA`d030b069465bd6a519bf3f10526442296f6c87dec5cd7a2e234a5e067a59b25d`,ZIP SHA`3a1994c200499803f97291692ec8cfa7c6664cff43c8cc6889580809ff42a7f5`; unsigned, tested with an existing interpreter. / 新包真实入口和依赖闭合；各组检查不相加冒充唯一覆盖。

The first uninstall no-residue assertion failed: the safety-preserving uninstaller retained generated bytecode. Main matched382 pyc files against the exact frozen source code and removed only those caches and now-empty directories inside this owned test installation. The original uninstaller then completed with zero residue. Initial failure and subsequent evidence are retained; daily install marker and browser profile/cache are unchanged. / 卸载保护保留缓存不是删除日常数据的授权；本轮逐项核验缓存后，仅清理本轮测试安装，最终正常卸载。

API objective total**1,748,671/5,000,000 tokens**,unknown0,reserved0. Local release preparation is complete, with external`RELEASE_NOTES.md`,installer,ZIP and checksums. No commit,push,tag or publication occurred; official0.1.2 and learning remain unchanged. The immutable installer's README is its build-time snapshot; this source report and external notes record later installed/independent acceptance without silently rebuilding. / 发布准备完成，尚未实际发布；安装器内文档是构建时快照，后续结果在源码和外部说明中记录，未静默重打包。
