# Decision Choice runtime verification / Choice 运行时验证

2026-10-12, unreleased source on `codex/dev-decision-api`.

## Contract / 合同

New v2 examples use one `current_step` Choice: `condition_met` continues; `condition_not_met` and `evidence_insufficient` return to the existing Main. Confidence and option probabilities are preserved for diagnostics, not converted to synthetic probabilities or passed through predicate thresholds. Omitted-format profiles retain predicate compatibility. Authentication, original input receipts, identity/geometry, deadline, cancellation and explicit `always_main` remain binding.

新 v2 示例采用单次三选一，满足继续，不满足或证据不足回原 Main。保留模型原始置信度及选项分布，但不以旧阈值再次否决 Choice。省略格式保留 predicate 兼容；原输入事实及身份、坐标、认证、取消、期限约束不变。

## Offline evidence / 离线证据

Main integrated regression: **486 passed in 49.60s**, recorded in `.superpowers/sdd/2026-10-12-choice-runtime/main-integrated-fixed.xml`. The first integrated run was **480 passed, 4 failed**: fixtures for newly Choice-enabled default examples still returned predicate responses. Those failures remain in `main-integrated.xml`; fixtures were corrected and six visual-default cases added before the complete selection was rerun.

Main 整合回归 486 项通过。首次 4 项失败为默认配置改用 Choice 后的旧 predicate 模拟响应不匹配；修复测试桩并增加视觉默认覆盖后重跑同组。首次失败记录保留，不计作首次成功。低置信度 `condition_met` 仍通过真实门禁调用链；另外两类不派发输入，原始分类保留于审核投影。

## Difficult real-API cases / 真实 API 困难样本

The production Choice provider was called once for each of 14 retained-image cases, without input dispatch or retries. Eight mismatches selected `condition_not_met`; two unobservable claims selected `evidence_insufficient`; four valid states selected `condition_met`. All matched Main's expected labels and routing. HTTP median was **229.123ms**, range **200.342–553.299ms**, with 46,633 input tokens.

真实提供者 14 次请求：8 个错误状态、2 个证据不足、4 个正确状态均符合 Main 标注。错误样本包括域名一字符差异、后缀差异、额外路径、错误字段、未全选、尚未搜索或页面错误；不足样本要求从截图推断不可见标签页及服务端结果。每个条件仅请求一次，未以重试筛选通过。

These are condition variants over five original requests and seven distinct images, labeled by Main, not an independently annotated accuracy benchmark. Actual partial selection, clipped long values and target occlusion remain uncovered by this batch. Evidence: `hard-cases.json`, `hard-dispatches.jsonl`, `hard-results.json` under the slice directory above.

这是五个原请求、七张不同图的条件变体，非 14 次独立实机操作，也非独立人工标注基准；不能宣称整体准确率 100%。真实部分选中、长文本裁剪与目标遮挡仍需补充。

## First live attempt / 首次实机

Run: `D:/AgentReviewAcceptance/native-focus-geometry-20261012-choice-1791771287458`.

Retained profile: `D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile`. Only the owned test window was launched. No profile/cache/cookie/extension/history deletion, copying or reset was performed.

`choice-round-1` automatically entered the Google URL and confirmed the homepage. At the next step, focus click and Ctrl+A completed; the empty Google search field's selection check returned `condition_not_met` (selected probability .50, confidence .25). No `java` text or Enter was dispatched. The runtime converted the review disposition to terminal `original_focus_partial_failed`, losing the structured Main handoff. This is a failed attempt, not a full-flow pass.

首次自动打开 Google；空搜索框全选核验被 Choice 判为不满足，未输入 java、未按 Enter。运行时将应交接审核的结果变为普通部分失败，结构化 Main 上下文丢失。此轮明确计失败，不能当作自动完成。

The hard-case positive and live failure have pixel-identical visible field content in corresponding frames. Each before/after pair differs only by 17 caret pixels. Original SHA bindings match. Detail crops differ by one row and full-frame surroundings differ; their causal effect is unknown. Both requests use the same empty-field-or-full-selection rule and the same generic temporal reminder. The API gives no explanatory reason. This establishes a classification inconsistency, not its root cause, and does not justify lowering thresholds or forcing approval.

补测正例与实测反例的对应字段区域像素一致，前后只有 17 像素光标闪烁差异，原图摘要匹配。裁剪相差一行、整图周边不同，尚无证据证明其导致分类反转；两者条件规则相同。不能把反转归因于已知提示词问题，也不能因此强行放行。

All 719 frozen app/script/config files remained unchanged during this attempt. The first host finished with `cleanup_verified=true` and exit 0; its window/profile were retained for the repair and continuous retest.

## Handoff repair and retest / 交接修复与复测

The common visual-field path now preserves authenticated requests, Choice results, image references and actual dispatch receipts for focus, selection and value refusals. Known partial input remains failed; genuinely unknown input remains pending/unknown. A diagnostic `main_handoff` reaches the actual ExecutionClient as `client_state=review_required`, without creating a success receipt or permission to resume/replay. Main must inspect the original evidence and explicitly close or replan.

公共字段路径保留焦点、选区、输入后值的认证拒绝和原输入事实。已知部分输入仍失败，真正未知仍 pending/unknown；只读 `main_handoff` 经最终客户端返回原 Main，不授予原后缀继续或重放权限。

Main final integrated regression: **595 passed in 53.90s** (`main-handoff-integrated.xml`); related client/partial-input tests: **61 passed in 3.28s** (`main-handoff-client.xml`). These supersede the earlier integrated selection; do not add overlapping historical counts. Worker verification was 239 passed across six related modules, independently inspected by Main and not counted as desktop acceptance.

Main 最终整合595项通过，另61项客户端／部分输入回归通过。前序486及worker239包含重叠，不累加为独立用例数。离线覆盖三阶段×两类拒绝、实际客户端精简回执、状态回读与相同交接事件去重；没有自动补发后缀。

Retest reused the same owned Edge HWND/PID, retained profile and a single repaired host session `session-6925229ba92248d88f446c5eec5daf2b`:

| Attempt / 轮次 | Actual result / 实际结果 |
|---|---|
| `choice-fixed-round-1` | About 19.8s to Main handoff. Google loaded; `java` was typed, but value Choice selected not met (.79 selected probability, .69 confidence). Enter was not dispatched. / 约19.8秒到交接；Google已加载、java已输入，值核验拒绝，未按Enter。 |
| `choice-fixed-round-2` | About 7.1s to Main handoff. URL was typed; value Choice selected not met (.52 selected probability, .28 confidence). Enter was not dispatched. / 约7.1秒到交接；网址已输入，值核验拒绝，未按Enter。 |

Main inspected both original images: expected text is visible. These are further false-rejection examples, not successful full tasks. In the second image the browser's focused address UI has expanded; full images and same-frame crops are retained for further evidence-presentation analysis. The API supplies no explanation, so the cause must not be inferred from its label alone. Neither attempt reached the first result link. The times measure time to failure/handoff, not task-completion speed, and exclude earlier debugging/preparation.

Main查看原图后确认预期文字可见，新增两条误拒证据；第二轮地址栏聚焦界面展开，原图与裁剪均保留供后续检查证据呈现。模型未提供理由，不能只凭标签认定误拒根因。两轮均未到达首个链接，不能宣称完整自动流程、连续稳定或性能收益。

Both repaired attempts delivered structured Main handoffs with original Choice and exact input prefixes. No retries were used to select a passing model answer. The owned window closed normally, the repaired host reported `cleanup_verified=true` and exited 0. All 719 frozen source/config files matched after the retest; the same profile remains present. No cache, cookies, history or extensions were cleaned. No commit, push, build or release was performed.

两次修复后交接均按合同返回；未以反复问模型筛选通过。仅正常关闭本轮窗口，宿主清理成功且exit0，719个冻结文件摘要未变；原资料目录与缓存保留。未提交、推送、打包或发布。

## Runtime failure closure / 运行时故障闭环

1. Failure: field review requests disappeared into generic partial failure. / 字段审核上下文被普通部分失败吞掉。
2. Invariant: a non-adopted authenticated Decision must reach Main together with the original input facts. / 认证的非通过判断必须与原输入事实一起交给Main。
3. Fix: shared visual-field exception/projection, task-plan terminal projection and ExecutionClient compact delivery. / 修于公共字段、计划终态及客户端回执。
4. Generality: covers all visual text fields, not a Google-only allowance. / 对所有视觉字段生效，非网站放行特例。
5. Regression: six Choice refusal combinations plus public-client/status/partial-input checks above. / 三阶段两类拒绝及公开客户端、状态、部分输入覆盖。
6. Safety: refusal still stops suffix input; no threshold reduction, success fabrication, replay or new authority. / 拒绝仍停止后缀，不降阈值、不伪造成功、不重放或增加权限。

Remaining: diagnose actual model/evidence inconsistency using retained hard positives and negatives, add real clipping/partial-selection/occlusion examples, then repeat complete continuous tasks. Do not restore mandatory UIA or lower thresholds to hide these failures.

剩余：以保留的真图正反例查清模型／证据不一致，补裁剪、部分选区和遮挡，再验收完整连续任务；不靠恢复必经UIA或降低阈值掩盖失败。

All 21 live requests can be inspected offline in `.superpowers/sdd/2026-10-12-choice-runtime/all-live-prompts.md`, with complete prompts, uploaded images and actual responses. Exports were reconstructed from authenticated records using unchanged provider code and matching original image/request digests; no API calls were made for export. Additional artifacts: `live-outcomes.json`, `source-freeze-fixed.json`, `live-first-decisions.json`, `live-fixed-decisions.json`, and the run directory's `isolated-browser-cleanup.json`.
