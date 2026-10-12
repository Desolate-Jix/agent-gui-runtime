# 执行模式全流程审查 / Execution-flow audit

日期 / Date: 2026-10-12
范围 / Scope: codex/dev-decision-api 源码；输入审核修复后的整个执行链。 / Source review of the complete execution chain after the input-readiness correction.

## 结论与边界 / Result and limits

Main 完成整链审查和两项分工复核，修复下列四处缺陷。最终49个相关模块 **786 passed in 55.31s**，无失败或跳过。本轮未操作桌面、调用真实 API、打包、发布或变更浏览器资料。 / Four defects were repaired. Main's final focused run passed786 checks across49 modules in55.31s, with no failures or skips. No desktop actions, live API calls, packaging, publication or browser-data changes occurred.

此前 [输入审核实测](INPUT_READINESS_20261012.md) 的 Google网址 → java搜索 → 首个普通链接是单轮3/3成功，早于下列修复，不计为当前源码的实机或连续稳定性通过。 / The earlier three-step live success predates these changes and does not certify the current source or continuous reliability.

## 当前执行链 / Current execution path

| 阶段 / Stage | 当前合同 / Current contract | 离线核对 / Offline coverage |
| --- | --- | --- |
| 用户任务与入口 / Task and entry | 新普通计划使用 task_plan.v3、visual-execution Choice profile 和获准的本步结果条件，保持同一连接。 / Use v3, visual Choice and approved current conditions on one connection. | public_input_defaults、task_plan_start_admission、execution_client |
| 选窗与启动 / Startup | 外层成功、身份一致且截图可用才入队；内部 focused 不覆盖截图失败。 / Require outer success and a usable bound capture. | execution_startup、pre_capture_failure_settlement |
| 定位 / Grounding | direct_visual 在 UIA/recall 前返回；绑定截图、坐标和窗口。 / Avoid implicit UIA/recall; bind frame/coordinates/window. | execution_direct_visual、task_plan_dispatch_target |
| 点击前 / Before click | 同原帧标注候选点，Decision 判断当前目标和动作可行性。 / Review the marked current candidate on its grounding frame. | candidate_current_scope、direct_visual_review_capture、action_review_single_authority |
| 输入准备 / Input readiness | 一张实际点击标注图，审核可输入及空/非空；不要求光标/焦点样式或500ms补图。 / One executed-click frame; no caret/style or extra500ms capture. | visual_input_flow_contract、visual_input_ready_runtime、visual_input_no_uia |
| 输入与文字结果 / Typing and value | 空框直接输入；获准替换非空框才全选核验；之后只比对规定文字。 / Empty fields type directly; replacement verifies selection; value checks compare requested text. | visual_empty_input、visual_text_value_decision、input_sequence_value_authority |
| Enter与结果 / Enter and outcome | 仅原请求需要时Enter；Choice标签决定继续或交原Main，不经旧概率阈值重判。 / Enter only if requested; Choice routes directly to continue or Main. | choice_execution_gate、choice_execution_projection、task_plan_goal_completion |
| 异常与收尾 / Interruption and cleanup | 认证已知前缀才结算失败；未知输入持原票据且不重放；只关闭明确归属窗口，保留profile/cache。 / Settle known failures, retain unknown tickets without replay, preserve browser data. | visual_enter_preparation_partial、task_plan_queued_cancel、execution_client_transport；收尾另作源码审查 / cleanup additionally reviewed in source |

当前图见 [视觉输入闭环](../development/VISUAL_EXECUTION_INPUT.md)。调用指南已纠正为当前v3和visual-execution profile；旧v2指南明确标为历史，不再作为普通执行默认。 / The maintained diagram and caller guide now identify the current v3 visual route; old v2 guidance is explicitly historical.

## 四项修复 / Four repairs

### 1. 候选审核混入未来任务 / Future context in candidate review

失败：短提示后实际HTTP仍带 remaining_plan 和未来输入文字，可能再次审核后续任务。被违反的合同是“只判断当前目标和当前动作”。公共provider现在仅投影当前候选/窗口事实、目标、动作类别及本步允许状态；完整请求仍本地认证。 / Candidate HTTP leaked future context despite a short question. The shared provider now projects current facts while retaining complete local request authentication.

[修改位置](../../app/judgment/openai_decisions.py) · [回归](../../tests/test_candidate_current_scope.py)：初始1失败4通过，修后5通过；不同未来计划的HTTP相同，但本地请求摘要不同且篡改拒绝。不是站点特例；不扩大条件授权，不改自定义/原生/历史合同。 / Tests verify identical HTTP but distinct authenticated local requests. No site-specific rule or broader condition authorization was added.

### 2. Decision前整图相等误拒 / Whole-image veto before Decision

失败：direct_visual另拍截图并要求全部PNG相等，无关动画即可阻止Decision。修复公共点击入口，让定位与审核复用同一绑定原图/坐标，仍检查原图哈希、身份与几何，不把旧坐标贴到新图。 / A second full-image equality check blocked review on unrelated animation. Grounding and review now share the bound original; source/identity/geometry checks remain.

[修改位置](../../app/api/action.py) · [回归](../../tests/test_direct_visual_review_capture.py)：首次4例失败；修后允许无关画面变化，文件篡改、窗口移动、进程出生身份改变仍拒绝。保留危险动作门禁与显式memory/delegated合同。 / Regressions cover animation and source/identity tampering. Dangerous-action and explicit memory/delegated gates remain.

### 3. Enter签发前停止卡住队列 / Stop before Enter issuance left the queue unresolved

失败：文字已核验，随后取消或超时；Enter尚未开始，却因旧结算无法识别此阶段而停在unknown/cancel_requested。通用输入/结算层新增prepare_search受控停止证明，消费端认证完整focus/type、策略、原值判断及身份才结算failed。 / A dedicated preparation-stop proof settles only an authenticated known prefix before Enter starts.

[输入层](../../app/execution/input_sequence.py) · [结算层](../../app/core/input_sequence_partial.py) · [回归](../../tests/test_visual_enter_preparation_partial.py)：初始8失败7通过，最终17例通过；相关窄组124通过。真实取消/到期才产生证明；任意签发异常、损坏认证、已开始或未知Enter仍unknown。不重放、不改原请求/回执，失败结算不授予新动作权限。 / Unknown dispatch and arbitrary errors retain the ticket. Original requests/receipts remain immutable and settlement grants no new action authority.

### 4. 最终哈希跨期限仍点击 / Final hash could cross the deadline

失败：最后一次输入前回调先查期限再读图，文件读取耗尽期限后仍可能点击。公共点击入口改为文件/窗口校验后，再验原审核期限与取消。 / Deadline/cancellation validation now runs after the final source-file and window checks.

[修改位置](../../app/api/action.py) · 回归 test_final_capture_validation_crossing_deadline_cannot_dispatch：先失败；修后相关14例通过。只关闭既有期限边界，不增加等待或模型请求。 / The new regression failed before repair;14 related checks then passed. No wait or model call was added.

## 验证证据 / Verification evidence

- [最终精确命令与49模块清单 / Exact command](../../.superpowers/sdd/2026-10-12-input-readiness/whole-flow-audit-final-command.json)
- [最终Main结果 / Final result](../../.superpowers/sdd/2026-10-12-input-readiness/whole-flow-audit-final.xml)：**786 passed, 0 failed, 0 skipped**。
- [首轮结果 / Initial run](../../.superpowers/sdd/2026-10-12-input-readiness/whole-flow-audit.xml)：539通过、2项旧合同测试失败。一个原生连续性用例补明确native上下文；旧拒绝clear_existing=false断言改为入队后运行时认证空框。未恢复旧限制；两模块复测53通过。 / Two stale tests were aligned to the approved native/visual split and empty-input contract without reverting production behavior.
- 新增 [贯通测试](../../tests/test_visual_input_flow_contract.py) 使用真实runtime、DecisionService、正式provider序列化及认证消费，仅模拟HTTP/桌面边界，覆盖空框/替换/拒绝/不足、标注图与请求数、重放认证和篡改。 / Integration coverage exercises actual runtime/service/provider/authentication with simulated external boundaries.
- 新缺陷红/绿记录保留在同一证据目录。capture-audit-green.xml为中间断言修正前的失败记录；最终以上列XML为准。各轮数量重叠，不相加。 / Retain first failures and intermediate attempts; counts overlap.
- 两名Sol分工检查前后半链；额外只读复核最终期限与Enter结算无新增具体发现。Main核对实际实现后完成最终测试。 / Bounded independent source reviews supplemented Main's implementation inspection and final checks.

## 剩余验证 / Remaining validation

本轮零真实API与桌面输入，不能据此声称Decision实际误拒率、体感延迟或连续稳定性达标。当前源码仍需用原保留profile验证连续使用、异常恢复与正常收尾，再按项目顺序验收冻结候选。无新安装包/发布。禁止清缓存、同图换ID抽到通过或重放未知输入。 / Live accuracy, latency and reliability remain unmeasured for these changes. Continuous retained-profile use/recovery and frozen-candidate acceptance remain. Do not clear cache, retry identical evidence for a favorable answer or replay unknown input.
