# 视频播放连续截图核验计划 / Video playback verification plan

> **已被新计划替代 / Superseded:** 当前开发与验收以[三张截图画面变化计划](2026-10-11-three-frame-picture-change.md)为准。下文保留旧设计和历史检查点；`temporal_playback.v1` 仅作历史兼容，不代表新三图路径或当前验收状态。 / The linked three-frame plan replaces this design. The text below preserves historical decisions and checkpoints; v1 compatibility does not validate the new path.

> 状态：用户已批准源码开发；Task1–3源码已接通，Main541项回归通过，证据读取优化后41项相关复测通过。用户明确实测稍后，Task4未执行。 / Source tasks1–3 are integrated;541 Main checks passed, followed by41 affected-path passes for ledger optimization. Live Task4 is deferred.
> For agentic workers: use the approved implementation loop after the user authorizes development. Reuse existing Sol ultra workers; preserve unrelated work. No commit, packaging or publication is part of this plan.

**Goal:** 用几秒内的播放器连续截图确认目标视频已开始播放，正常情况由 Runtime 自动结束步骤，减少 Main 接管。 / Confirm that the intended video has started using a short, bounded capture sequence, allowing ordinary completion without Main intervention.

**Architecture:** 在既有结果核验入口增加显式 `video_playback` 类型。复用维护截图、原请求、证据哈希和审核续行机制；本地先核验，不足时把时序证据一次交给已配置 Decision，再不足才回原 Main。不建立第二个执行器，不将该逻辑应用到普通网页跳转。 / Add a dedicated verification type to the existing runner, using local evidence first and at most one temporal Decision assessment before existing-Main review.

**Tech stack:** 现有 Python 截图、图像处理、限定区域 OCR、视觉定位接口及 Decision 客户端；不新增本地大模型依赖。 / Existing Python capture, image processing, bounded OCR, visual grounding and Decision clients; no new local model dependency.

**Spec:** 本文为用户已批准的连续截图设计；现已开发源码，Task4真实测试按用户最新选择后置。 / Approved design; source implementation and offline checks are complete; live Task4 is deferred.

## 已核对的现状 / Current integration points

- `task_plan_contract.py` 当前只接受 `agent_judgment`、`native_condition`；后者核对 UIA 条件，不应伪装成视频证明。 / Existing native proofs are UIA-specific and must remain distinct.
- `task_plan_verification.py` 与 `task_plan_backend.py` 分别产生、复核证明；两处都要识别新的证明类型，不能只在前者写 success。 / Both production and adoption must authenticate the new proof.
- `task_plan_observation_capture.py::capture_followup` 已验证窗口、尺寸、原图和新采集身份，可复用。它不能硬中断底层同步截图，晚返回须判超时并单独计时。 / Reuse capture guards; late synchronous returns cannot be advertised as hard-cancelled.
- 现有 Decision 上传限 1–2 张图，普通追加观察为原 after + 最新 observation。provider 明确要求缺时序证据时拒绝 ongoing playback；当前没有独立的视频时序证据合同。 / Current static-image roles do not constitute a formal temporal playback contract.
- Codegraph 在当前工作树未初始化，本次仅按上述源码只读核对，没有建立索引。 / The worktree has no Codegraph index; direct reads were used without initializing one.

## 拟定行为 / Proposed behavior

### 1. 只绑定本次目标播放器 / Bind the intended player

只有显式声明“确认视频开始播放”的步骤启用。复用本次截图上已有且仍有效的播放器区域；从搜索卡片进入新页面后，卡片坐标不能当播放器坐标。若尚无区域，用现有 Luna 接口最多进行一次只读定位，输出主播放器、内容区域、可见进度/控件区域及有依据的遮挡区域。不派发点击、hover、滚动或键盘输入。 / Reuse a valid current-frame region or perform one read-only Luna localization. Search-card coordinates cannot identify a player after navigation; verification dispatches no input.

区域绑定当前窗口/进程、截图 ID、尺寸、目标标题或其他可见身份。多播放器归属不明、明显广告、遮挡、页面滚动/布局移动时不把像素差当播放；保持不确定并说明原因。不得把首屏广告的播放算成目标视频成功。 / Bind identity and geometry; ambiguous players, advertisements, occlusion and layout movement cannot satisfy the requested video condition.

### 2. 连续采样并尽早结束 / Sample and stop early

- 拟定采样间隔 500ms；至少 3 张有效新帧，实际时间跨度至少 1 秒。每张记录真实采集时刻，不以帧数冒充秒数。 / Proposed interval500ms, minimum three fresh frames spanning at least one second.
- 通常观察 2–3 秒，最多采 7 张；证据充分立即结束。整个核验调度预算拟定 8 秒，包含区域定位、本地采样和最多一次 Decision，不因等待、重连或分支切换重置。 / Aim for2–3s observation, at most seven frames, within one proposed8s scheduling budget including localization and optional Decision.
- 已有播放器区域的目标是 2–3 秒完成；需要额外 Luna 定位的目标是 5–8 秒。它们均为待实测目标。截图/HTTP晚返回不采纳，并报告实际耗时；暂不承诺硬实时上限。 / These are targets, not measured guarantees; late results are rejected and actual elapsed time is retained.
- 本步骤使用明确的较短首次采图等待，避免先固定等2秒再开始新观察；其他步骤默认等待不改，测量仍从动作派发计入完整链路。 / Avoid stacking the old wait onto the new observer; preserve unrelated defaults and report complete action-to-result timing.

### 3. 两类证据共同判断 / Combine motion and player state

本地对播放器内容区域做缩小、分块像素差，记录变化比例、空间分布和连续变化次数。排除已识别的控件、字幕/弹幕覆盖区域与加载标记；不能把整个播放器都遮掉来获得“干净”结果。阈值在正负样本集上预注册、校准并冻结，不在单次失败后反复调低到通过。 / Measure distributed, sustained content changes with explicit masks and calibrated thresholds; never tune a failing live case until it passes.

| 证据 / Evidence | 结论 / Outcome |
|---|---|
| 目标身份有效，播放时间/进度在多个采样间隔持续增加，且无暂停、加载、广告或错误冲突 / Valid identity and sustained progress without conflicting state | 本地确认 playing；静止镜头也可通过 / Local playing proof, including static scenes |
| 内容区域持续变化，并有可信播放状态辅助，但时间/进度不可确认 / Sustained content motion with incomplete progress evidence | 保留时序证据，交一次 Decision，不凭像素差单独成功 / One temporal assessment, not motion-only success |
| 只有转圈、弹幕、字幕或页面变化 / Only spinner, overlay text or page motion | 不能成功；明确加载且预算有余才继续观察 / No success; bounded waiting only for declared loading |
| 明确暂停、结束或播放错误 / Explicit pause, ended state or error | 返回具体未播放原因，不重复点击 / Report the observed state without input replay |
| 静止画面且进度不可见 / Static scene with hidden progress | uncertain，不直接判暂停或失败 / Uncertain, not automatically paused or failed |

可见暂停按钮只是辅助证据，不单独证明播放；时间跳跃一次也不算持续推进。识别不到控件时不为显示控件额外移动鼠标。若实测证明某种“分散持续画面变化+明确播放状态”的组合足够可靠，可另审放入本地快速通过规则；首版不先承诺它不会误判。 / A pause icon or a single seek jump is insufficient. Hidden controls do not trigger mouse movement. Broader local motion-only shortcuts require separate evidence before adoption.

### 4. 用一次时序判断完成兜底 / One temporal assessment when needed

已有 Decision 时：给它两个有代表性的采样帧（优先已渲染视频的前后帧），连同真实间隔、区域、遮挡、局部变化及进度读数；完整3–7帧链保留本地。新增版本化 `temporal_playback.v1` 绑定，记录原 after、原输入 ID、采样顺序/时间、所有哈希和策略，不把新采样改名冒充原 after。 / Send at most two representative images plus authenticated temporal metadata, retaining the full sequence locally and the original after-frame identity.

provider 只对这个新合同使用时序问题，判断“所采集区间内目标视频是否呈现播放推进”，不承诺持续到未来，也不修改普通单图问题。接收方重新核对所有绑定及证据。一次判断仍不确定/拒绝或没有 API，返回原 Main；提前打包连续帧、差异和具体原因，免去 Main 逐次找图。Decision 失败不触发新采样/新请求循环。 / Apply a temporal question only to the new contract. Authenticate at adoption; uncertainty returns one complete evidence packet to existing Main, without repeated judgments.

本地证明仍服从显式 `always_main` 审核配置，不能以确认视频的名义放宽下一动作门禁。 / Explicit always-main policy and subsequent action gates remain in force.

## 实施顺序与验收 / Implementation and acceptance

### Task 1 — 纯图像/时序判定 / Pure temporal analyzer

新增 `app/execution/video_playback_evidence.py` 和 `tests/test_video_playback_evidence.py`。接口拟为 `evaluate_playback_sequence(frames, region, observations, policy)`，只返回证据、状态与原因，无截图/网络/输入权限。 / A pure analyzer produces evidence and state without native or network dependencies.

- [x] RED/GREEN覆盖纯时序证据、静止+进度、暂停/加载/广告状态、单次seek、仅运动、重复帧、时间/区域/遮挡参数及损坏证据；真实遮挡、多播放器和广告识别仍属Task4。
- [x] 实现分块差异、证据组合和未知状态；通过上述回归，不把静止或缺读数强行分类。

### Task 2 — 有界采集与原票据自动结算 / Bounded capture and settlement

新增 `app/execution/video_playback_verification.py`，修改 `task_plan_contract.py`、`task_plan_backend.py`、`task_plan_verification.py`；复用维护截图和原票据机制。新增 `tests/test_task_plan_video_playback.py`。 / Add a bounded driver and authenticate the new proof in both verification and adoption.

- [x] 明确 v2 扩展类型及能力声明；不支持的旧宿主提前拒绝新类型，旧计划行为保持原样。
- [x] RED覆盖预算包含定位/采集、达到最小时间跨度才可通过、取消/重连不重置预算、过期结果不采纳、原输入未知不核验、窗口变化停止、证据篡改/伪造成功被拒绝。
- [x] 实现 `judged_by=video_playback` 的真实本地证明，backend 重新验证原帧与策略；成功原票据结算后自动继续，任何分支均不重放输入。

### Task 3 — 时序 Decision 与完整审核包 / Temporal Decision and review packet

按新合同修改 `app/judgment/evidence.py`、`openai_decisions.py`、`service.py` 与现有审核/证据交付入口；新增 `tests/test_video_playback_decision.py`。只扩展显式时序入口，保留普通1–2图协议和现有拒绝约束。 / Add one explicit authenticated temporal route while preserving static-image behavior.

- [x] RED覆盖当前静态合同不接受冒充时序、帧乱序/旧截图/时间篡改、代表帧与完整链不一致、超时/拒绝/无API、always_main、调用至多一次。
- [x] 实现问题与回执；测试 Main 可一次取得完整证据，正常本地证明不调用 Decision。

### Task 4 — 流程与真实收益验证 / Real workflow and latency validation

- [ ] 先完成离线单元/合同与原图回放，再从全新数据根执行 Google→Bilibili→二次元→首个目标视频；增加一个不同播放器的普通视频场景。只在用户允许恢复测试后执行。
- [ ] 同一会话覆盖播放、暂停、加载后播放、弹幕、广告/遮挡、恢复与清理；保留首次失败，不用多次重跑掩盖误判。
- [ ] 分开报告定位、采样、OCR/差异、Decision、Main接管和完整任务用时。关键负例中任何错误自动通过均阻止推广；达不到2–3秒目标则拆解真实瓶颈，不以放宽条件换速度。
- [ ] Main 通过后再独立验收同一冻结候选；同步 README、TASK_PLAN、架构和当前状态。安装/发布另行处理。

## 范围边界 / Scope boundary

本轮设计只解决“播放已开始”的时间性确认，保留 API 可选和学习模式独立。它不能证明整段视频之后不缓冲，也不能只凭有限截图保证不存在所有形式的动画广告；证据不充分时明确不确定。本批新增源码和离线测试，没有桌面操作、付费调用或版本修改；实机性能与困难负例尚未验收。 / This source slice verifies observed playback onset, not future uninterrupted playback. Offline checks do not establish live latency or difficult-negative accuracy.
