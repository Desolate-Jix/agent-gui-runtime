# 视频核验真实验收 / Live playback acceptance

本轮用户明确批准真实桌面和已配置的 Luna / Decision API 测试。只用项目截图和动作接口、新浏览器窗口及新数据，不登录、发送、下载或修改账户。源码未发布。 / The user authorized fresh desktop and configured API tests through maintained project interfaces. This is unreleased source acceptance.

## 首轮结果 / First attempt

证据根 / Evidence: `D:/AgentReviewAcceptance/video-playback-live-20261011-01/trial-02`.

- Google 首页、搜索哔哩哔哩、打开官网、搜索二次元：四步自动通过。 / Four navigation/search steps passed automatically.
- 第五步已点击打开第一个实际视频，但播放核验返回 Main：`video_playback_player_ambiguous`，核验阶段 2496ms，零播放样本、零时序 Decision。原 after 是仍在加载的新页白屏；后续只读截图已经显示视频画面。整条不计通过。 / The fifth click opened the selected video, but the locator received the loading blank frame and returned uncertainty. The whole flow did not pass.
- 暂停尝试未派发：`agent_grounding_target_region_changed`。控制条隐藏时模型选中动态画面，原有区域新鲜度检查拒绝。此项是未完成测试，不能算暂停负例通过。 / The pause click was refused before dispatch because the proposed dynamic region changed; paused-state rejection was not exercised.
- 测试窗口 `window_closed`，宿主 `cleanup_verified=true`，CLI exit 0、stderr 空；1082 个 Python 源文件首轮前后 SHA 相同。 / Owned window and host were cleaned; the source freeze remained unchanged.

## 已修复的客户端合同 / Client contract repair

实测前发现 CLI 仅接受 review_packet v1–v3，会拒绝新 v4。现已支持 v4 的摘要及专属字段交叉绑定，完整采样图引用与原 after 分开；不增加磁盘读取或模型调用。首个 RED 1 fail，Main 两个客户端模块复测 **83 passed / 2.30s**，见 `main-cli-v4.xml`。 / CLI v4 validation and complete-sequence delivery references were added. Main reproduced the passing narrow suite without adding model work.

测试调用脚本另有闭包复用已关闭管道的问题，发生在浏览器动作之前；空会话已通过维护 stop 正常清理，测试脚本改用持久对象管理连接。此准备开销不计作产品推理时间。 / A caller-script pipe lifecycle error occurred before GUI input and was cleaned separately; it is not product inference latency.

## 故障合同 / Failure contract

1. 失败：新页面已打开但过早的白屏原图无法定位播放器。 / Failure: the original post-click image was captured before the player appeared.
2. 不变量：加载过渡不得直接被视为目标歧义的最终证据；需要在既定预算内读取当前状态。原输入和原 after 不能被替换。 / Invariant: bounded current-state observation must preserve the original receipt and after image.
3. 修复位置：共用视频核验入口；后续第二轮真实 YouTube 就绪图已验证该入口。 / Fix location: common verifier; the subsequent YouTube run exercised readiness before localization.
4. 通用性：所有异步加载的网页播放器都会遇到该过渡，不依赖 Bilibili 选择器。 / Applies to asynchronous players without site-specific selectors.
5. 回归：白屏到播放器、持续加载、截图数量和时间预算、原证据绑定。 / Regression covers loading transitions, bounds and provenance.
6. 安全：不重放输入、不提高判断通过阈值、不放宽点击区域新鲜度。 / No input replay or weakening of action gates.

## 当时未完成项（最终状态见下） / Earlier pending items (superseded below)

加载入口修复后的真实复测、第二个实际视频网站、成功派发的暂停/恢复及同候选独立验收尚未完成。有限样本不支持准确率或整任务提速百分比结论。 / Repaired live runs, a second site, actual pause/resume and independent acceptance remain pending; accuracy and end-to-end speedup are not established.

## 第二轮 / Second attempt

证据 / Evidence: `trial-03`。Main 相关路径 **95 passed / 20.06s**；该次测试开始时未留源码快照，不能证明95项覆盖当时最终冻结文件。第二轮实测自身1082个Python文件前后SHA一致；后续最终155项另有完整前后源码冻结。 / The95-test run lacks a test-start source snapshot and cannot authenticate the exact candidate; live source stability and the later155-test freeze are separate evidence.

- Bilibili 再次自动完成前四步；成功定位并采集四帧，完整 v4 图像通过公开 CLI 交付；最终8.044s超时，未调用时序Decision。Main审阅四帧后，以原票据review/continue结算为completed，明确计一次Main审核。 / Bilibili required one explicit Main review after the8.044s automatic timeout.
- 实际定位3.853s；四次本地观察合计2.892s，截图合计约0.28s，差异分析合计0.115s。控制条隐藏，四帧全为unknown/null，第3帧已跨2.627s但仍等待7帧上限。 / Full-player OCR and continued sampling, rather than capture itself, consumed the remaining budget.
- YouTube官方Big Buck Bunny视频：新入口成功穿过两张白屏就绪观察并定位，采到三张播放图；7.990s观察超时，未调用时序Decision。原计划取消并保留实际已打开页面的结果，不能计自动通过。 / The loading repair was exercised on a second real site, but temporal assessment still lacked budget.
- 浏览器window_closed、host cleanup_verified=true、CLI exit0、stderr空。 / Window and host cleanup completed.

当时修复方向（现已实现并复测）：没有可信播放控件时不反复执行无法形成本地证明的OCR；API可自动采用时，三张unknown且无时间读数、跨度至少1s的样本即可进入单次时序Decision，不强求采满7张。无API及always_main保留原完整采样，8秒上限和通过阈值不变。 / The next narrow change reserves assessment time when local proof is unavailable, without relaxing evidence thresholds.

## 最终候选与第三轮 / Final candidate and third live attempt

证据 / Evidence: `trial-04`，session `session-62ec5fca3eee48d589cf6d2ee23ccfb8`。Main最终相关五模块 **155 passed / 21.00s**（JUnit20.971s，0失败/错误/跳过），`main-final-scheduling-rerun.xml`；测试前后及此次实测后1082个Python源码SHA一致，见 `final-verified-source-before.json`、`final-verified-source-after.json`、`trial-04/source-after.json`。此前3项失败是新测试在未满足原3帧/1秒门槛时要求负面结论，修正测试时序后复测通过；首次失败 `main-final-scheduling.xml` 保留。没有放宽生产门槛。 / The final155-test freeze and live run share unchanged source hashes; the initial three test-timing failures remain preserved.

最终命令 / Final command: `python -m pytest -q tests/test_task_plan_video_playback.py tests/test_video_playback_observer.py tests/test_video_playback_public_decision.py tests/test_task_plan_observe_client.py tests/test_task_plan_client.py --junitxml=D:/AgentReviewAcceptance/video-playback-live-20261011-01/main-final-scheduling-rerun.xml`。解释器为 `D:/agent-gui-runtime/.venv/Scripts/python.exe`，工作树为 `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`。

| 实际项目 / Actual check | 结果 / Result |
| --- | --- |
| Google搜索结果 / Google results | condition_met=.99，但needs_agent_review=.45进入灰区；Main核对原图后沿原票据续行。 / One explicit Main review despite the high condition score. |
| Bilibili目标视频 / Target Bilibili video | 3帧、7.797s核验；时序Decision调用一次，condition_met=0，needs_agent_review=.42。原图均为00:00和播放三角，正确未确认播放；Main结算失败，整计划4/5。 / Correctly did not certify the sampled non-playing state; whole plan failed. |
| 后续显式播放 / Explicit play attempt | 新图已自动开始播放，Luna返回request_absent；未派发，未重试点击。 / The control was absent after delayed autoplay; no input. |
| YouTube官方BBB / Official YouTube BBB | 两张就绪观察后3帧，6.990s；一次时序Decision condition_met=.75、needs_agent_review=.01。Main审阅标题卡→淡出→云景的完整原图链后确认并续行；1次Main，不算自动通过。 / Completed with one Main review. |
| 暂停/恢复 / Pause/resume | 首次request_absent：控制条已隐藏。随后Tab显示控制条后立即重试不同新命令，定位成功但agent_grounding_target_region_changed，未派发；暂停负例及恢复均未完成。 / Absent then freshness-refused; no pause-negative or resume acceptance. |
| 清理 / Cleanup | window_closed；host cleanup_verified=true；CLI exit0、stderr空。 / Owned browser and host closed normally. |

以上7.797s/6.990s是视频核验阶段（定位、截图、分析、Decision与调度），不是Decision纯请求用时或整条任务时间。完整调用方空档、模型耗时和请求表分别保存在各轮 `timing-summary.json`，不从端到端体感中删除。 / Verification-stage timing is distinct from provider-only and end-to-end time; caller gaps remain visible in the timing records.

## 本轮修复边界 / Repair boundaries

- CLI认证并交付v4完整序列，绑定原输入、原after、账本引用与摘要。白屏就绪图独立保存，定位只调用一次；就绪与播放新图合计最多7张，共享8秒预算。 / V4 delivery and bounded readiness preserve the original action identity.
- 无可信暂停双竖线时跳过全播放器OCR，返回unknown/null；可自动采用的API且非always_main，在3个unknown/null样本跨1秒后进入一次Decision。无API/always_main保留完整采样上限。 / Reserve assessment time when local proof is unavailable.
- 跳过OCR会减少本地文字负例识别：无控件的暂停/错误等文字可能从已知负例降成未知。未知不能本地通过；时序图及负面约束仍送Decision；无API转原Main。有控件仍作完整blocker检查，已知负例继续拒绝。 / Local text-negative availability is reduced, not silently claimed unchanged; unknown never locally passes.
- 第二轮B站本地观察2.892s是实测瓶颈之一；YouTube该项仅52.6ms，主要为定位4.787s及未及时进入判断，不能把两站都归为OCR慢。 / The sites had different bottlenecks.
- 点击新鲜度、判断阈值、最少帧数/跨度、原请求续行与不重放要求未放宽。 / Action gates and evidence thresholds remain intact.

## 当前结论与后续 / Current conclusion and remaining work

本轮证明真实时序Decision已能在预算内发出并返回，也保留了未播放负例；未证明全自动正例、暂停/恢复、复杂广告/遮挡准确率、2–3秒本地路径或完整任务提速。尚未进行同候选独立实机验收、构建或安装回归，未提交/推送/发布。 / Real temporal requests now complete within the budget, but autonomous positive and continuous-use acceptance remain incomplete.

下一优先项是从本轮证据确认动态播放器控件的新鲜度拒绝原因，设计不削弱门禁的最小修复；再校准时序正例为何落入灰区（保留固定阈值，不重试刷通过），补暂停/加载负例与同候选连续流程。Main闭合后才交独立验收，最终再集中打包。 / Diagnose dynamic-control refusal, then temporal positive uncertainty; complete negatives and continuous use before independent acceptance and packaging.

## 暂停拒绝的原图核对 / Pause refusal evidence

最终visible暂停候选并未选中整播放器：bbox=(32,668,40,40)，point=(52,688)；门禁加8px后核对[24,660,80,716]，56×56。source 13:47:43.123有白色暂停双竖线和控制栏，执行前current 13:47:47.985控制栏已隐藏；按钮框内亮白像素166→0。区域变化78.38%远超2%上限。这不是已证明的误拒绝；约4.862秒的定位与复核间隔超过了控件可见期。 / The40×40 target was accurate, but disappeared during the4.862s source-to-gate interval. The freshness refusal was justified, not a proven false positive.

1. 失败：暂停动作未派发，暂停/恢复测试未完成。 / Failure: no pause input, so pause/resume coverage is incomplete.
2. 根合同：模型定位的可见目标必须在真正输入时仍存在；瞬时悬浮控件不能假定在等待期间持久。此次门禁保持了合同，动作准备没有确保控件存续。 / The action gate upheld target freshness; preparation did not keep the transient control available.
3. 修复位置：待设计在共用动作准备/定位层处理显隐控件；播放只读核验器不应偷偷悬停或输入。 / Any visibility preparation belongs to explicit action handling, not the read-only verifier.
4. 通用性：悬浮工具栏、播放器与临时菜单同类；不能按网站降低区域阈值。 / Applies to transient controls across applications, without site-specific gate weakening.
5. 回归：用已有原图建立控件消失与仅背景运动两类对照，再验证显式保持可见/焦点方案及超时拒绝；该修复尚未实现。 / Replay disappearance separately from background-only motion before any implementation.
6. 安全：当前拒绝正确，无输入；不得将这次失败记成播放负例通过，不通过重复点击或跳过新鲜度获得成功。 / No input was dispatched; preserve the failure and existing gates.

## 最终计时拆分 / Final timing separation

时序Decision本身的HTTP请求：Bilibili **575.70ms**，YouTube **656.64ms**；含本地服务处理分别585.60ms/667.77ms，均包含网络/服务耗时，不是纯推理。它们已包含在7.797s/6.990s核验总时长中，不能再相加。 / Temporal HTTP calls took575.70ms and656.64ms, nested in the reported verification intervals.

最终session共Luna11次（9次动作定位+2次播放器定位），HTTP合计43.194s；Decision6次（4静态+2时序），服务合计3.673s。完整session就绪到finish **414.653s**，其中等待调用返回81.507s、调用方读取/审核/排查等空档333.146s（包括153.654s的暂停诊断前空档）。这些是本轮测试体感的一部分，不能隐藏，也不能全部归为模型推理。 / Session wall time was414.653s, with81.507s awaiting calls and333.146s between calls, including diagnostics. These are not model-only costs or a clean benchmark.

原件：`trial-04/timing-summary.json`、`caller-calls.json`、`caller-events.json`；最终正常退出和清理读回单独保存为 `trial-04/cleanup-final.json`。首轮和第二轮计时分别保留，不把跨版本、不同视频和Main介入拼接为受控提速结论。 / Timing and cleanup records remain separate for each candidate; this is not a controlled speedup benchmark.
