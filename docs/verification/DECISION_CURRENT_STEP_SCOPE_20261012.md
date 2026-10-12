# Decision 当前步骤结果范围 / Current-step result scope

2026-10-12，未发布源码，分支 `codex/dev-decision-api`。本次只收窄结果审核提示与上传上下文，阈值不变。 / Unreleased source. This slice narrows outcome-review prompts and transmitted context without changing thresholds.

## 修改 / Change

- `after_action` 只判断当前声明条件及当前证据，不重复检查前序流程或要求后续步骤提前完成；不上传完整 `review_context`、全局目标和剩余计划。动作证据按允许字段投影，递归剔除历史字段。 / Assess only the current declared condition and evidence; omit workflow history, global goals and remaining-plan context from after-action wire content.
- `needs_agent_review` 只针对影响当前结果的歧义、遮挡、异常和错误。普通导航、链接、可选按钮本身不构成接管理由。 / Review targets actual issues establishing the current result, rather than ordinary navigation or optional controls.
- 完整原请求仍在本地认证、摘要及账本中保留。动作前审核、原生焦点/值证据、视频/动态内容专用判断、输入门禁和阈值不变。 / Full local authentication and ledger bindings remain; pre-action, native-field and temporal predicates, input gates and thresholds are unchanged.
- 本轮配置：before pass `0.80`，after pass `0.80`，after review `0.70`，通用 pass/fail `0.90/0.10`；与本轮开始前一致。 / These thresholds match the pre-change configuration.

## 离线验证 / Offline verification

新增范围回归先失败 `7 failed / 1 passed`，实现后 `8 passed`。Main 扩展回归首次 `483 passed / 2 failed`：两项仍要求上传旧计划上下文；更新为“远端省略、本地继续认证”的合同后，最终 **485 passed，0 failed，0 skipped**（pytest 控制台 7.47s，JUnit 7.437s）。保留首次结果，不把改后的通过覆盖旧失败。 / New tests demonstrated failure before implementation. Two obsolete wire-context expectations in the broader run were then updated while retaining local authentication checks; the final run passed all 485 cases. Initial failures remain recorded.

```powershell
D:\agent-gui-runtime\.venv\Scripts\python.exe -m pytest -q tests/test_decision_current_step_scope.py tests/test_openai_decisions.py tests/test_native_focus_evidence.py tests/test_native_value_evidence.py tests/test_native_field_freshness_evidence.py tests/test_decision_after_action_thresholds.py tests/test_decision_before_action_threshold.py tests/test_decision_threshold_adoption.py tests/test_adaptive_decision_policy.py tests/test_task_plan_review_context.py tests/test_task_plan_goal_completion.py tests/test_video_playback_decision.py tests/test_video_picture_change_decision.py tests/test_dynamic_content_decision.py --junitxml=.superpowers/sdd/2026-10-12-current-step-decision/main-offline-final.xml
```

冻结 provider SHA256：`4fa1277d24f901168ba25a002d613b22d5c182e725da2d511f706e1b1356d6b9`。实测后相同；四个 Decision 配置样例的 SHA256 与本轮修改前相同。 / Provider source and all four example-profile hashes remained frozen during live checks.

## 实测 / Live results

同一独立 Edge 窗口、同一 Runtime 会话，Luna API 定位、Decision API 判断。先完成离线验证，再执行真实输入；均经项目维护的截图/动作接口。 / One isolated Edge window and runtime session, using Luna grounding and Decision judgments through maintained project interfaces.

| 检查 / Check | 结果 / Result |
| --- | --- |
| 第一轮 / Round 1 | `isolated-round-1`：输入 Google 网址 → 搜索 java → 打开首个普通结果，3/3 自动完成，无 Main review/continue。 / All three steps completed automatically, without Main intervention. |
| 网址精确值 / URL value | condition `0.98`、review `0.00`，采用 / adopted |
| java 精确值 / Search value | condition `0.99`、review `0.00`，采用 / adopted |
| Google 首页 / Homepage | condition `1.00`、review `0.00`，HTTP `251.7875 ms` |
| java 搜索结果 / Results | condition `1.00`、review `0.00`，HTTP `325.8607 ms` |
| Java 目标页 / Destination | condition `1.00`、review `0.01`，HTTP `277.9145 ms`，自动完成 / automatic completion |
| 第二轮 / Round 2 | `isolated-round-2`：地址栏点击后原生字段读取报 `text_field_geometry_changed`，停在第一步；未开始新文本、全选或 Enter。 / Native field read failed after the focus click, before the typing suffix. |
| 第二轮 Decision / Round 2 Decision | 动作前 condition `1.00`、review `0.00`，已采用；没有调用该轮 after-action Decision。 / Pre-action approved; no after-action Decision was reached. |

第一轮末图中 Java 正文已显示，右上角翻译浮窗没有导致结果接管；第二轮点击后浮窗消失、网址仍为 Java。只能证明字段几何合同报错，尚不能仅凭截图判定是否未取得焦点或确认浮窗就是根因。 / The destination content was visible alongside a translation popup. The repeat stopped with a field-geometry error after the popup disappeared. Screenshots alone do not establish focus failure or prove the popup caused the geometry mismatch.

本轮共 **11 次 Decision 请求**（首轮 10、第二轮动作前 1）。上表 HTTP 用时只包括供应商请求，不等于完整流程体感速度；运行指标标记 `measurement_status=not_collected`，不声称整链性能收益。旧目标页 `0.68/0.83` 与本轮 `1.00/0.01` 不是同图对照，不能据此给出准确率或因果提升百分比。 / HTTP timings exclude the full workflow. There is no controlled same-image accuracy or end-to-end speed benchmark.

## 第二轮失败合同 / Repeat-run failure contract

1. 失败 / Failure：首步已点击聚焦，读取原生字段几何失败，未继续键入。 / Focus click completed; native geometry read stopped the input suffix.
2. 不变量 / Invariant：首次焦点读取时，当前原生控件框必须有效、在绑定窗口内且包含原点击点；这里没有重复比较 Luna 整个候选框。`describe_target/read_index=1` 失败不能证明发生过前后位移，且回执未记录失败控件框，尚不能区分无效框、越界或点击点不在当前焦点框内。对应 `app/agent/windows_text_field_reader.py` 的 `read_focused_at_point`、`_describe_target`、`_relative_rect`。 / The first focused-field read requires a valid in-window native rectangle containing the original point, not equality with the Luna box. The failing rectangle was not recorded, so the precise cause remains unresolved.
3. 修复位置 / Fix location：本次未修改原生读取公共层；后续应先复现并核对该层，而非继续修改结果提示词或降低阈值。 / No native-reader change in this slice; inspect the shared reader before changing prompts or thresholds.
4. 非站点特例 / Scope：错误发生在通用地址栏字段读取阶段，不是 Java 网页结果审核。 / This is a shared field-read issue, not a Java-page outcome judgment.
5. 回归 / Regression：本次 485 项保护了提示词、认证和阈值。现有 `tests/test_windows_text_field_reader.py` 和 `tests/test_input_sequence_focus_partial.py` 有错误焦点框与聚焦后拒绝的覆盖，但本轮未重跑，也尚未建立该真实几何错误的最小复现。连续验收仍未通过，不以首轮成功替代。 / Prompt regression is covered. Existing native-reader/partial-sequence negative tests were inspected, not rerun in this slice; a reproducer for this live failure remains open.
6. 安全影响 / Safety：未放宽原生几何检查，未重放部分动作，第二轮没有新文本和 Enter。 / The geometry gate remains, with no replay of partial input or typing suffix.

## 准备与收尾 / Preparation and cleanup

准备阶段出现过 Main 调用脚本的宿主归属错误与 Windows 拒绝前台激活；它们单列保存，不归因于 Decision 推理。闲置宿主在确认零输入后经维护接口停止；用户手动切到测试窗口后选择成功。 / Preparation included caller orchestration and foreground-activation failures. An idle zero-input host was stopped through the maintained interface; selection succeeded after the user focused the test window.

测试通过显式 `--user-data-dir` 使用以下目录，正常 `WM_CLOSE` 只关闭已核验归属的本轮窗口；宿主 `cleanup_verified=true`，客户端 exit `0`。没有删除本轮 profile，也没有清理日常浏览器资料。 / Explicit profile isolation, owned-window-only normal closure and verified host shutdown; both test and personal browser data are retained.

```text
D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile
```

原始证据根目录为该 profile 的父目录：`events.jsonl`、`decision-summary.json`、`round2-first-failure.json`、`isolated-browser-owner.json`、`isolated-browser-cleanup.json`、`idle-client-cleanup.json`、`final-verification.json`。活跃测试会话为 `runtime/session-6eabae3dbe1d4aaa9c5265d90957d00e`。离线 XML 与测试脚本保存在工作树 `.superpowers/sdd/2026-10-12-current-step-decision/`，前序红绿记录在 `2026-10-12-decision-current-step-scope/`。 / Raw evidence and initial failures are retained in these locations.

**结论 / Conclusion：本次当前结果范围修改已有离线与单次完整自动流程证据；连续稳定性仍受原生字段几何错误阻挡。未提交、推送、打包、安装或发布。 / Current-result scoping has offline and one complete automatic-run evidence; continuous reliability remains blocked by native field geometry. No commit, push, package, installation or release.**
