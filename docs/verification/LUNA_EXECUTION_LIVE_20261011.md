# Luna 连续执行实机记录 / Luna continuous execution live record

## 范围和当前结论 / Scope and current result

用户当前目标授权低风险桌面测试：通过执行模式输入Google地址，搜索哔哩哔哩，进入网站搜索二次元并播放首个视频，之后再选其他真实场景。普通Luna API定位、独立Decision结果判断，不准备本地视觉模型、不使用Codex原生Computer Use。当前修复后两轮完整五步均completed，各有4步Decision与1步Main审核；播放加载自动复核已在窄场景和完整流程分别通过，另有真实文档网站拒绝/恢复验证。下文按顺序保留首次失败和修复证据，不把重跑通过改成首次成功，也不计作安装版正式验收。 / The active goal authorizes the requested low-risk real flow and additional scenarios using ordinary Luna grounding and separate Decision assessment. Two repaired five-step flows completed, each with four Decision-verified steps and one Main review. Automatic playback loading passed both a narrow trial and the full flow; a documentation scenario exercised refusal and recovery. Earlier failures remain recorded in chronological order; reruns are not first-attempt or installed-release passes.

工作树 `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`，分支 `codex/dev-decision-api`。本记录对应未发布源码；既有安装器不变。 / This record covers unreleased source in that worktree and branch; published installers are unchanged.

## 原始证据 / Original evidence

- `D:/AgentReviewAcceptance/luna-live-20261011-01`：PTY 客户端的 launch/select/capture、纯图片与混合回执交付。图片 SHA256 为 `76784f3efc50569421d038ef8e7fdce2b3369e0fb14bb7b904afe37e114d1a67`，保存图片与原图一致。关闭本轮窗口后 `finished.cleanup_verified=true`。 / PTY client launch/select/capture and both image-delivery forms; exact image hash and verified cleanup.
- `D:/AgentReviewAcceptance/luna-live-20261011-02/submitted-plan.json`：经真实 stdin 管道提交的五步计划，1775 UTF-8 字节。 / Five-step plan submitted through a raw stdin pipe.
- 同目录 `caller-events.json`：所有客户端回执、原计划等待、明确 review/continue 和最终清理。 / Client receipts, original wait, explicit review/continue and cleanup.
- 同目录 `focus-readonly-probe.jsonl`：两个原点只读采样，未点击或输入。 / Two read-only samples at the same point, without input.
- 会话目录 `session-0eb539c80c7e42d79e5dfd4fd39e076e`：原 commands、agent-commands、截图、Decision 及计划账本。 / Original command, screenshot, Decision and plan ledgers.

## 首次流程 / First attempt

1. 第一次会话 launch 2833.124 ms、select 202.916 ms、capture 56.26 ms；这是命令耗时，不是从用户要求开始的总耗时。 / Command timings, not user-to-result latency.
2. 长计划经 Windows PTY 被截断，JSON 解析失败。运行时只读状态确认 `task_plan_run=null`、`pending_ids=[]`、Decision `used=0`，计划没有执行。独立无 GUI/API 探针发现此 PTY 路径最大完整单行 510 字符，511 及以上截断至 510；分块写入不解决。原始管道中 2048 字符 ASCII 及 6122 字节中文样本均完整、SHA256 相同。后续直接驱动维护的 `scripts/execution_client.py`，没有新建执行器。 / PTY truncation happened before plan admission; a separate probe reproduced it, while raw pipes preserved exact UTF-8 payloads. The maintained CLI remains the executor.
3. 第二会话 Edge 同时出现主窗口和“已阻止这些扩展”提示，launch 返回歧义。通过维护的 discover/select 和项目截图选择本轮主窗口，未修改扩展设置。 / Edge exposed two windows; explicit discovery and selection resolved the ambiguity without changing extension settings.
4. `google_home` 地址栏输入及跳转成功：组合输入 10416.814 ms（focus 7804.877、type 379.467、search 2135.685）；Luna HTTP 5887.282 ms，服务端处理 2840 ms。Decision 总耗时 3073.156 ms，HTTP 2517.997 ms，服务端处理 468 ms。Decision 判定目标成功概率 .98，但额外介入概率 .34，返回 `off_plan_intervention_gray`。Main 查看原图，确认 Google 输入框可用且扩展提示不覆盖下一目标后，按原包 review 并继续；此步包含 Main 介入，不能冒称自动通过。 / Address entry and navigation succeeded, but Decision requested review. Original-image Main review and continuation are recorded separately from automatic success.
5. `google_search`：Luna HTTP 3229.741 ms，返回搜索框 bbox `[361,456,688,53]`、点 `[700,482]`。当前控件命中只得到八层 Pane，预检在 47 ms 拒绝，`action_executed=false`。未重复点击、未输入搜索词，计划正常终结为失败。 / The correct visual target was rejected by the native writable-field precheck before dispatch; the plan terminated as failed.
6. 通过项目门禁点击本轮窗口 Close，窗口关闭后原 after 截图不可用，动作回执仍保留失败状态；随后 discover 确认该 Edge 窗口与弹窗均消失。宿主最终 `cleanup_verified=true`。关闭动作不是图像核验成功，不改写原回执。 / Gated close had no after-image because the window disappeared; subsequent discovery verified removal and host cleanup succeeded. The original failed observation receipt is retained.

本批第二会话共 3 次普通 Luna 定位（包括关闭）和 1 次 Decision，Decision 未知派发 0；未暴露密钥。旧记录的 12 次是历史批次统计，不是本轮新次数。 / Three grounding requests including cleanup and one Decision; zero unknown Decision dispatches. Historical batch counts are separate.

## 输入预检缺陷 / Field-readiness defect

- **Failure:** 可见搜索框已被 Luna 正确定位，原生预检却只看到容器，阻止了第二步。 / Correctly grounded field rejected as a container.
- **Root invariant:** 同一窗口、进程和原点的 UIA 首次命中可能尚未提供精确字段。只读重采实际呈现 Pane → 横向 Group / mixed Document → ComboBox；现有重采资格只覆盖半宽且半高的 mixed 容器，漏掉前两种状态。 / Initial native point evidence can be incomplete; the existing bounded readiness classifier excludes these observed states.
- **Fix location:** 共用 `probe_local_focus_target` 的只读就绪分类；不添加网站专用定位、Chrome flags 或输入重试。 / Shared native focus readiness, without site-specific targeting or action replay.
- **Why not app-only:** 其他 Chromium 页面和原生容器首次暴露控件时也需要同一精确字段证明。 / The same precise-field contract applies beyond Google.
- **Regression:** 新增16项现场路径与拒绝边界回归；原38项基线通过，修复前54项中10失败，修复后54项通过。Main首次8模块组合273通过、12失败，失败全部为旧结构化测试未声明学习路线却预期原生定位，触发视觉模型stub缺少`parsed`；单跑也复现。普通执行把target作为视觉约束是已有明确合同，不能为修测试恢复慢扫描；测试将明确选择公开`agent_mode=learn`，保留原生门禁断言并与普通视觉默认合同一起复验。原失败XML保留于`focus-repair-main.xml`。 / Sixteen regressions added; 38 baseline passes, ten expected failures before repair, 54 passes after repair. Main's initial combined run had 273 passes and 12 failures in an old native-route fixture using the now-visual ordinary route. Preserve the failure record and explicitly exercise the public learning route without reverting ordinary execution behavior.
- **Safety:** 仍须同窗、同原点、正确几何和最终精确可写 Edit/ComboBox；容器不授权输入，明确只读/密码/身份变化不应重采放行。 / Containers never authorize input; exact writable-field, identity and geometry checks remain required.

## 剩余验收 / Remaining acceptance

相关离线回归与两轮完整源码流程已完成；当前剩余重点是非阻挡提示触发Main审核的条件质量，以及冻结候选单项、连续使用和独立验收。保留未知/失败回执，不能为压低Main次数放宽身份、坐标或结果阈值。已有小样本不足以给出泛化准确率或整链加速百分比；不继续重复同一路径来换取一次零Main结果。 / Relevant offline regressions and two full source flows are complete. Remaining work concerns review-condition quality for nonblocking hints and frozen-candidate single, continuous and independent acceptance. Preserve failures and unknown receipts without relaxing input or result boundaries to reduce Main counts. Small samples do not support general accuracy or speedup percentages; repeated runs should not be used to chase one zero-Main result.

## 第一轮修复后实机 / First repaired live attempt

Main相关10模块最终 **341 passed in 2.71s**，XML为`luna-live-20261011-02/focus-repair-main-final.xml`。此前12项夹具失败未抹去；修正只给原生门禁测试显式选择公开学习路线，普通执行视觉默认回归一并通过。 / Ten related modules passed; the original fixture failures remain recorded. Only the native-gate fixture's declared route changed, and ordinary visual-default tests passed alongside it.

新数据根`D:/AgentReviewAcceptance/luna-live-20261011-03`，同一维护CLI/会话、原五步计划、同一Decision配置。Google地址输入/跳转、Google搜索、打开Bilibili三步均`judged_by=decision`、`authenticated_decision`自动成功，三步间没有Main审核或输入指令。第四步仍未派发输入而失败，所以整轮仍不计通过。 / The first three steps automatically passed with authenticated Decisions in one session and no intervening Main review. Step four failed before input, so the full run still failed.

| 步骤 / Step | Luna HTTP ms | Decision 总 ms / total | 结果 / Outcome |
|---|---:|---:|---|
| Google 首页 / home | 4029.763 | 2750.861 | 自动成功 / automatic success |
| Google 搜索 / search | 3154.660 | 313.783 | 自动成功 / automatic success |
| 打开 Bilibili / open | 2992.997 | 1323.840 | 自动成功 / automatic success |
| Bilibili 搜索框 / search field | 2928.963 | 未调用 / not called | 点击前拒绝 / rejected before click |

原件见该目录`caller-events.json`、`timing-summary.json`和`session-65157914f6c142a7b421807d48161288`。第四步raw Group为`[4,80,1387,1836]`，超出1032像素高的可见窗口；祖先Document为`[4,80,1402,948]`且mixed。现有重采资格要求raw矩形完全在窗口内，因此15ms后直接拒绝。随后同窗同点两次只读均得到可写Edit `[520,102,300,20]`。这是网页内容容器合法向下延伸的新边界；拟仅修正只读重采的可见范围判断，不调整最终字段bbox或输入授权。 / The document's content container extends below the viewport and is excluded by the current readiness classifier. Subsequent same-point probes found the precise Edit. Only container readiness geometry needs adjustment; final field geometry and input authorization remain strict.

本轮4次Luna、3次Decision、未知Decision派发0；本轮自建窗口通过`close_launched_window`返回`window_closed`，宿主`cleanup_verified=true`，CLI退出0。 / Four grounding calls, three Decisions, zero unknown Decision dispatches, graceful owned-window close and verified host/CLI cleanup.

## 第二轮修复与键盘门禁 / Second repair and keyboard guard

只读容器就绪分类已修复向下延伸的 raw Group：使用其窗口内可见部分，左、右、上边界仍严格，最终可写字段仍须完全在窗口内。新增14项边界回归；Main相关10模块 **355 passed in 2.69s**，原件`luna-live-20261011-03/focus-repair-main-final.xml`。 / The readiness classifier now considers the visible portion of a downward-extending raw Group; other edges and final writable-field geometry remain strict. Fourteen boundary regressions were added, and Main's ten-module run passed 355 tests.

第四个新会话位于`D:/AgentReviewAcceptance/luna-live-20261011-04`，前三步完成，其中Google搜索因Decision介入灰区经过一次原图Main审核。Bilibili搜索框focus和填写均成功；Enter阶段返回`key_dispatch_failed / internal keyboard field changed`，旧回执保持未知，不能重写为成功或零输入。 / In session 04, the first three steps completed, with one Main review for a Decision gray zone. Bilibili field focus and typing succeeded; the Enter guard then failed. Its original unknown-input receipt is retained.

- **Failure:** 搜索词已填写，未观察到搜索结果页。 / The query is filled, but no results page was observed.
- **Root invariant:** 键盘门禁把完整bbox纳入严格身份比较。原check_focus高度21、check_input高度20；后续4次只读采样为21，其余身份、文字摘要、source和selection相同。原报错未保存门禁当时的current快照，因此不能声称已经逐字段还原报错瞬间；现场数据证明1像素变化确实存在，并可离线复现旧门禁拒绝。 / The guard compares exact bounding boxes. Recorded and later read-only samples show the same field alternating between 20 and 21 pixels high. The failing guard did not record its current snapshot, so its instantaneous comparison is not fully recoverable; the observed jitter reproduces the strict-identity rejection offline.
- **Fix scope:** 仅私有`focus_reflow`绑定键盘目标允许同实例四边各1像素误差，原锚点仍须在当前字段内；值、source、进程、窗口、RID、追加选区与其他输入门禁保持严格。 / Only privately bound focus-reflow keyboard targets may tolerate one pixel per edge, with the original anchor still inside the current field. Other identity, value, selection and input guards remain strict.
- **Evidence:** `keyboard-bound-readonly-probe.jsonl`及该会话`agent-commands/trial-exec-8eb0b0c33decfd9585752d567ae563b2.json`。最初未在独立读取器绑定窗口的探针失败也保留在`keyboard-readonly-probe.jsonl`，不作为产品字段失败证据。 / The bound read-only probe and original command are retained; an initial unbound diagnostic probe is kept separately and is not treated as product field-failure evidence.

此时仍未完整播放首个视频，不能记作全流程通过。 / The first-video playback flow has not yet passed.

第四会话共4次Luna、3次Decision，Decision未知派发0。原计划取消停在`cancel_requested`，未把键盘未知回执改判；随后通过维护CLI正常finish，`cleanup_verified=true`、exit0、stderr空，独立只读确认原HWND已不存在。此轮按宿主停止后的窗口消失记录，不计主动`close_launched_window`成功。原件另见`post-stop-window-state.json`。 / Session 04 made four grounding calls and three Decisions, with zero unknown Decision dispatches. Cancellation remained pending because of the original unknown keyboard receipt. The maintained CLI then stopped normally with verified cleanup and exit zero; a separate read-only check found the original window gone. This is not counted as an explicit owned-close success.

键盘修复新增18项回归，原30项基线通过；新增后RED为2 failed/46 passed，修复后48 passed。Main相关13模块 **462 passed in 3.12s**，原件`luna-live-20261011-04/keyboard-repair-main.xml`。源码SHA256为`7aa8dace99eb96780d25a111cfebde6cad8abc4090734fa9036f7f258d1fbb98`；未改变历史未知回执分类。 / Eighteen regressions reproduced the defect before repair. Main's thirteen-module integration passed 462 tests. The source hash is recorded, and historical unknown receipts were not reclassified.

第五会话窄回归（`D:/AgentReviewAcceptance/luna-live-20261011-05`）已完成Bilibili填写→Enter→首个实际视频点击。搜索由Decision自动确认；播放首次后图仍是黑色加载区，Decision交回Main。沿同一原请求两次只读observe取得不同视频场景和字幕，Main据此审核成功，再原wait continue至completed。此项证明搜索/播放及原请求观察链路，不冒称播放由Decision自动确认。主流程仍待本轮后续连续复测和清理。 / The narrow search/playback flow completed. Decision automatically verified search; Main verified playback using two authenticated follow-up frames after the initial loading frame. The original wait then reached completed. This validates keyboard search and evidence-preserving observation, not fully automatic playback verification; full-flow regression and cleanup follow.

## 完整流程、自动加载与其他真实场景 / Full flow, automatic loading and another real scenario

第五会话随后在同一窗口、同一MCP会话完整执行原五步，前四步均由Decision自动确认，最后播放仍经Main两帧观察审核，原wait继续到completed。动态搜索结果已经变化，两轮分别打开了当时真正排第一的视频，未使用固定视频坐标或标题。两轮共7次Luna和7次Decision、未知Decision派发0；主动owned-close返回window_closed，宿主cleanup_verified=true、CLI退出0。 / The same-session full five-step flow completed with four automatic Decisions and a final Main playback review. Search results changed between runs, and each current first video was selected without stored coordinates or titles. Seven grounding and seven Decision calls were recorded, followed by verified owned-window and host cleanup.

原五步start到末步原after图为38.991秒；首个Luna开始至末个Decision结束为39.225秒。另有108.373秒从原末图到Main审核返回，包含人工检查和追加观察，不计作模型服务耗时。详细逐步来源见第五会话`timing-summary.json`；这不是未经审核的全自动39秒完成，也不能换算为通用加速比例。 / Start to the last original action frame took 38.991s; first grounding start to the last Decision ended at 39.225s. Main observation/review then added 108.373s. These clocks and scopes are distinct, not a claim of an automatically completed 39-second task or a general speedup.

第六会话`D:/AgentReviewAcceptance/luna-live-20261011-06`明确为播放步骤声明`wait_policy`和可见加载状态，沿既有接口复测，没有改阈值或等待器源码。初判`condition=0/loading=1/error=.02/review=.01`、disposition=observe；两次只读截图后仅追加一次Decision，`condition=.97/loading=0/error=0/review=0`，自动completed。两次Decision内部总耗时分别1487.530和1060.158ms，首次计划返回约14.36秒；这次无Main审核、无输入重放。此前计划未声明wait_policy而出现still_progressing=not_requested是调用配置缺项，不能归为等待器源码故障。 / Session 06 explicitly declared loading using the existing API. It automatically observed, reassessed once and completed without Main review or input replay. The earlier missing loading predicate was a caller-plan omission, not a runtime waiter defect.

同会话真实Python官网文档流程：地址输入及Library Reference点击自动成功；预设Built-in Types链接不在当前画面，Luna返回request_absent，运行时在输入前拒绝并终结failed。Main核对原图后新建“Quick search填写→打开精确结果”计划；搜索结果条件不在冻结auto_conditions中，按既有机制零API交Main审核，目标页再由Decision自动确认。原失败保留，复规划不是盲重试；未修改网站布局或开启额外权限。本轮6次Luna、5次付费Decision，另1条未批准条件的skipped记录，未知Decision派发0；owned-close、宿主清理及CLI退出0均通过。 / The documentation flow automatically reached the library page, then safely rejected an absent link. A new explicit search plan reached the exact Built-in Types page; the unallowlisted search condition used Main review without an API call, and the final page was Decision-verified. The first failure remains recorded. Six grounding and five paid Decision calls, plus one skipped assessment, ended with verified cleanup.

## 最终完整复测 / Final integrated rerun

第七会话位于`D:/AgentReviewAcceptance/luna-live-20261011-07/session-e173f772bc0349f6908c63b705ab4ceb`，沿同一维护CLI提交完整五步，仅把第六会话已验证的加载声明加入播放核验；没有调整生产代码、Decision阈值或输入门禁。最终`status=completed`，依次为Google首页Decision、Google搜索Decision、Bilibili首页Decision、二次元搜索Main、首个视频播放Decision。 / Session 07 reran the complete five-step plan through the maintained CLI, adding only the proven playback-loading declaration. Production code, Decision thresholds and input gates were unchanged. The first three steps and final playback were Decision-verified; search results required Main review.

搜索页Decision判定`condition_met=1`、`visible_error=0`，但`needs_agent_review=.28`落入`off_plan_intervention_gray`。Main读取原包截图，确认右上登录提示未覆盖目标，按原请求review和continue。此处保留一次Main介入；不能声称全流程零Main。 / Search was successful, but a .28 intervention probability required review. Main inspected the original image, confirmed the login hint did not cover the target, and explicitly continued the original request. This is not a zero-Main full flow. 截图中存在登录提示，但概率回执没有解释，不能证明它是灰区的唯一原因。后续同图只读探针的原声明为.04、补充非阻挡状态声明为0；两次均通过只说明存在波动，不构成误判率统计或重复请求的运行策略。 / The hint was visible, but the probability-only receipt does not establish it as the unique cause. A later read-only same-frame probe returned .04 with the original declaration and zero with a bounded nonblocking-state declaration. This demonstrates variability, not an accuracy estimate or permission to repeat live judgments until they pass.

播放原输入票据为`trial-exec-6a16f0d800fc99d260378a8fd53d13dc`。首判`condition=0/loading=1/error=0/review=.07`、disposition=observe，Decision内部总耗时420.506ms；既有观察器执行两次只读截图，仅追加一次判断，`condition=.95/loading=0/error=0/review=0`、disposition=continue，393.299ms，自动完成且未再次点击。最终认证观察图`task-plan-observations/task-observation-035cc05e493241d887ade4ee6cfcab4d.png`的SHA256为`7ee2f387f70009e890002bdb973d6c96d4d6177c6a0f5424b57a42a24b1dce7f`。这些是判断阶段耗时，不是整条用户任务耗时。 / The original playback ticket was retained. Initial loading assessment took 420.506ms, followed by two bounded read-only captures and one 393.299ms reassessment that automatically completed the step. No click was repeated. The authenticated final-frame hash is recorded; these are assessment-stage timings, not whole-task latency.

最终状态无pending输入。五次普通视觉Luna调用各attempts=1，六次付费Decision（五步首次判断加播放复核一次）均validated=true；两条路线合计11次模型请求，Decision `used=6/limit=8/unknown_dispatches=0`。`final-integrated-close`返回`window_closed`；随后`finished.cleanup_verified=true`，CLI退出0、stderr空，最新`caller-events.json`已保存。Sol独立只读核对计数与状态一致；这不是独立实机验收。本轮未构建、未安装、未推送或发布；下载仍为原preview.3。 / Final status had no pending input. Five ordinary grounding requests each used one attempt; six validated paid Decisions comprised five initial assessments and one playback reassessment, totaling eleven model requests across the two routes. The Decision budget was six of eight with zero unknown dispatches. Owned-window close and host cleanup succeeded; the CLI exited zero without stderr. Sol independently checked the recorded counts and states, not live acceptance. No build, installation, push or release was performed.
