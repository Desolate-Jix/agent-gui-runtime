# 空框直接输入验收 / Verified empty-field input

2026-10-12；源码未发布，安装器未改变。 / Source-only, unreleased; installers unchanged.

## 结果 / Result

同一保留独立 Edge profile：地址栏输入 Google 网址 → 搜索 java → 打开第一个普通结果，三步自动通过，最终页面为 Java | Oracle（https://www.java.com/zh-CN/），没有 Main 接管。最终截图同时显示翻译提示，但主体内容已加载，未对提示做额外操作。 / The retained-profile flow completed all three steps automatically and reached Java | Oracle, without Main takeover. A translation prompt was visible while the destination content was loaded; it was not manipulated.

- 地址栏非空：field_content=nonempty，仍全选替换。 / Nonempty address bar retained select-all replacement.
- Google 搜索框为空：field_content=empty，原 clear_existing=true 自动使用实际 false；selection_dispatch=not_started，只有一次文字派发，无 after_selection 请求。 / The empty search field automatically skipped selection and dispatched text once.
- 输入后文字比较及独立 Enter 检查保持。空框分类加入既有焦点请求，不增加 HTTP 往返。 / Text comparison and the separate Enter binding remain; content classification shares the focus HTTP call.
- 显式 clear_existing=false 已由公开命令与 v3 计划接通；仅认证空框允许直输，非空或不确定交 Main，任意追加未开放。 / Explicit no-clear is admitted, but only authenticated empty fields can type directly; append is not supported.

## 证据 / Evidence

本轮目录 / Current run:
D:/AgentReviewAcceptance/native-focus-geometry-20261012-empty-fixed-01

final-summary.json、events.jsonl 和 runtime/session-ec519c5678b2413286a11c1836919b64/agent-commands/ 保留正式回执。 / These artifacts retain production receipts.

沿用资料目录 / Retained profile:
D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile

只正常关闭身份核实的本轮窗口；host exit=0、cleanup_verified=true、stderr为空。没有删除、重置或清理浏览器资料及缓存。 / Normal owned-window closure, host exit 0 and verified cleanup, with no profile/cache deletion or reset.

## 离线验证 / Offline verification

Main 实际运行的四份通过 XML 位于 .superpowers/sdd/2026-10-12-choice-runtime/： / Four passing Main-run XML reports:

- empty-input-contracts-01.xml：399 passed。
- empty-input-integration-04.xml：70 passed。
- empty-input-partial-02.xml：110 passed。
- empty-input-final-partial.xml：13 passed。

去重共572例，失败和错误0。覆盖空/非空/不确定、显式不清空、错误文字不回车、认证篡改、真实队列中断结算与取消、旧原生/predicate合同。 / 572 distinct passing cases cover content routing, no-clear, incorrect values, authentication, queue settlement/cancellation and legacy contracts.

首次红测7 failed/1 passed；整合发现夹具未复用维护请求的默认值与摘要，已修夹具而未放松生产回执。另将空框新检查限定于显式 content_check，保留旧路线。 / Initial red: 7 failed, 1 passed. Integration fixtures were aligned with maintained request normalization without loosening receipt validation. Empty classification is restricted to the new route.

## 故障闭环 / Failure closure

1. Failure：前轮空框 Ctrl+A 后被 Decision 交 Main，显式 false 又被 visual_input_append_unsupported 拒绝。前轮目录 native-focus-geometry-20261012-marked-live-01 保留，不能改记成功。 / Preserve the earlier selection and admission failures.
2. Invariant：空框不需要选择字符，实际派发必须匹配已认证字段状态与回执。 / Empty fields need no selection; dispatch must match authenticated evidence.
3. Fix：共享 judgment、visual input、keyboard binding 和 partial receipt 层。 / Common judgment/input/receipt layers.
4. Scope：不依赖 Google 适配器，适用于普通可读文本输入框。 / No site-specific adapter.
5. Regression：上列空/非空/损坏证明及中断测试。 / The listed contract regressions.
6. Safety：未取消焦点、身份、坐标、原文、独立 Enter、取消或期限绑定；损坏策略仍 unknown，原输入不重放。 / Existing bindings remain; corrupted strategy is unknown and input is never replayed.

仅证明本轮完整任务通过，不能据此声称所有站点或长期连续运行稳定。旧失败、固定截图对照与本轮实机证据分别保留。阈值未改，未构建、安装或发布。 / One complete live run is not a general reliability benchmark. Earlier failures and retained-image tests remain separate; no thresholds or packages changed.

## 追加体感复测 / Subsequent repeat

同日按用户要求再次复测，保留同一profile，目录 native-focus-geometry-20261012-empty-repeat-02。选窗返回内部focused但外层failed（capture_window_occluded）；测试驱动过早仅按内部focused提交计划，动作也在截图处停止，原输入被记为unknown，取消停在cancel_requested。没有重新派发原输入，未进行第二次完整重跑；Google网址输入尚未完成。本次失败与上轮3/3成功分别保留，不能宣称连续稳定通过。需先修正测试驱动要求外层成功且有可用截图的条件，并查截图前失败的未知结算合同，再实测。窗口正常关闭，宿主exit0/cleanup_verified=true，缓存保留。 / The repeat failed at capture_window_occluded. The driver admitted the plan based only on nested focused status despite outer selection failure. Runtime input became unknown and cancellation remained pending; no replay occurred. This is a failed repeat, not consecutive reliability proof. Review driver admission and pre-capture failure settlement before further live runs. Normal cleanup preserved the profile/cache.
