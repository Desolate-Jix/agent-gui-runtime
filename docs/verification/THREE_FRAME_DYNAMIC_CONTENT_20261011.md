# 三图动态内容核验 / Three-frame dynamic-content verification

2026-10-11，未发布源码 `codex/dev-decision-api`；安装器、版本和远端未更新。 / Unreleased source; no installer or publication changes.

## 实现 / Implementation

视频使用 `video_playback`；通用接口使用 `dynamic_content`，必填 `target_description` 和获准的确切 `decision_condition`。两者共用原运行器：输入与render grace完成后，至少等1秒采首图，相邻截图完成间隔至少500ms，恰好三图、一次Decision，采样/判断/采用共用8秒预算。三图全部上传，原after独立认证但不上传。 / Video and generic target-content checks share one runner, exactly three fresh frames and one assessment within the existing8s budget.

只判断目标内容变化，排除外围动画与按钮显隐；没有额外播放器定位、控件、OCR或本地进度成功判定。无API或always_main仍采三图交原Main；拒绝、不确定、迟到不重放输入。显式新profile采用通过≥0.80、转Main≥0.70，原错误/动作前门禁不变。 / Target change is the criterion; no extra grounding or control/progress proof. No-API and uncertain cases retain original Main review without replay or new authority.

`temporal_visual_change.v1` / `dynamic_content_binding.v1` 将目标描述绑定进请求和采用认证；视频v2及历史v1各自保留语义。 / Generic target descriptions are authenticated without reinterpreting historical video evidence.

## 离线证据 / Offline evidence

Main三图/阈值相关组合：190 passed +229 passed，见 `D:/AgentReviewAcceptance/video-picture-change-20261011-01/main-integration.xml` 与 `main-runtime.xml`；这是两个检查组，不代表整个仓库。

Generic集成首次272 passed /1 failed：新fixture误用helper的step-0，实际计划为clock，运行时正确拒绝身份不匹配。只修fixture后交付2项通过；运行时最终38项通过。三份XML按测试身份取最新结果，共280个不同用例无剩余失败，见 `D:/AgentReviewAcceptance/dynamic-content-20261011-01/main-results.json`。不把worker重叠测试相加。 / The integrated failure was a test identity mismatch. Affected reruns passed; latest outcomes cover280 distinct cases, not the whole repository.

## 真实结果 / Live results

| 场景 / Scenario | 核验总时间 / Verification | Decision HTTP | 结果 / Result |
|---|---:|---:|---|
| YouTube Big Buck Bunny |5.234s|1.758s|condition0.99，自动采用，零Main审核 / automatic pass|
| time.is主时钟秒数 / seconds digits |5.483s|1.299s|45→46→47，condition1.00，自动采用 / automatic pass|
| Python文档正文 / static introduction |4.225s|0.977s|三图SHA相同，condition0，未采用，交Main结算失败 / correct negative|

核验时间包含等待、截图、API和采用，不是纯推理时间。视频调用方总时间13.532s，时钟16.608s，另含Luna地址栏定位、输入和导航。时钟服务总时间2.307s与HTTP1.299s不同，不能把初始化等服务开销称为网络时间。每例只发一次Decision。 / Full caller times include grounding/navigation; verification and HTTP timings are distinct. These observations are not a controlled speedup or accuracy benchmark.

原始证据 / Raw evidence:

- `D:/AgentReviewAcceptance/video-picture-live-20261011-01/trial-01/timing-summary.json`
- `D:/AgentReviewAcceptance/dynamic-content-live-20261011-01/trial-01/timing-summary.json`
- 各trial的caller-calls/events、session下原图/Decision/账本、source-before/after与cleanup-final。密钥不写入报告。 / Original calls, receipts, images, assessments, source manifests and cleanup are retained without credentials.

## 首败和边界 / First failures and limits

1. Google→Bilibili流程停在Google搜索框定位：Luna返回框在输入框上方，0.99置信度也未放行，字段门禁在输入前拒绝。原图与推理图均2560×1400、映射1:1，未证明本地缩放错误；未削弱门禁或硬编码修正。 / Wrong model coordinates were rejected before input; this complete flow did not pass.
2. YouTube暂停定位时控件已隐藏，返回absent；K/k不在维护键集合，输入前拒绝。没有真正暂停，暂停/恢复和加载负例未验收。 / Pause/resume was not reached, so it is neither a classifier pass nor failure.
3. Main首次在静态负例continue前启动新计划被拒，但遗留ready trial。原wait随后完成continue，新start及owned-close仍被阻挡，cancel返回runner未知。宿主finish退出0、stderr空、cleanup_verified=true；源码前后无漂移。首败保留，公共启动原子性修复与复测另附。 / A rejected premature start left a ready trial without a runner, blocking later work; host finish completed cleanup. Admission repair is recorded separately.
4. 目标变化不能证明音频、静止镜头播放、业务完成或未来连续性。广告、遮挡、多目标和慢加载样本不足，不能宣称通用准确率。 / Declared target change is not blanket task success or a general reliability guarantee.

## 后续 / Next

拒绝启动残留已修复且同会话复测通过，详见下节。后续补暂停/恢复、加载及复杂干扰；Google/Bilibili定位链按原证据独立修复。未做独立冻结候选实机或打包。 / Admission repair passed same-session retesting below; missing negative/grounding coverage remains before independent acceptance or packaging.

## 拒绝启动残留修复与复测 / Rejected-start repair and retest

- **Failure**：旧负例已review为failed但runner仍waiting；过早start先写ready trial，随后runner拒绝，遗留记录阻挡后续任务和正常owned-close。
- **Invariant**：被活动运行器拒绝的新计划不得持久化一个可阻挡会话的活动trial。 / A rejected new start must not leave an active trial.
- **Location**：公共 `TaskPlanRuntime.control` 普通start延迟创建；`WorkflowRunner.start` 在已有active锁和活动门禁通过后调用私有prepare回调。学习路线无回调时保持原逻辑，不加第二运行器。 / Trial creation now follows admission under the existing runner lock.
- **Why common**：适用于所有caller plans，与Google、播放器或dynamic_content无关。 / This is application-independent admission behavior.
- **Regression**：新增 `tests/test_task_plan_start_admission.py` 覆盖success/failure审核后的提前start、锁拒绝、旧绑定回读。聚焦RED3 fail/1 pass→GREEN4 pass；Main实际执行 `python -X utf8 -m pytest -q` 的start_admission、task_plan_runner、workflow_runner、task_plan_adaptive_review、dynamic_content_runtime/delivery、video_picture_change_delivery七模块：**121 passed /16.42s**。XML位于 `D:/AgentReviewAcceptance/task-plan-start-admission-20261011-01/main-integrated.xml`。
- **Safety**：原wait必须显式continue，原窗口/身份/输入门禁不变。提前start无派发、无残留；没有删除旧证据、自动继续失败步骤或增加危险输入许可。 / Existing continuation and action gates are unchanged; no replay or authority expansion.

修复后用全新trial-02，**同一宿主和浏览器**按原故障顺序实测：静态三图相同、Decision condition0→Main review failure→故意提前start被拒且task-plans/task-plan-runners JSON前后逐字相同→原wait continue到failed→新时钟计划完成（13→14→15，condition1.00，零Main审核）→owned-close成功→finish cleanup_verified、exit0、stderr空。源码前后SHA无漂移。 / Fresh same-session reproduction passed the exact rejected-start sequence, subsequent task and cleanup.

复测核验时间：静态6.206s（HTTP2.042s）；时钟3.931s（HTTP0.806s，调用方总计12.349s）。保留首轮与复测的全部差异，不选最快样本冒称稳定延迟。证据 `D:/AgentReviewAcceptance/dynamic-content-live-20261011-01/trial-02/{timing-summary,admission-snapshots,cleanup-final}.json`。 / Retain both runs rather than treating the fastest sample as typical latency.

限定只读复核未发现新接线缺陷；不是独立实机验收。旧start幂等回读清空内存_enabled_run、Windows锁异常分类仍是既有待查项；本修复不声称跨文件崩溃/磁盘失败事务原子性，也未迁移历史幽灵记录。 / Read-only review found no new wiring defect; legacy replay state and lock exception classification remain separate issues, and crash-level multi-file atomicity is not claimed.
