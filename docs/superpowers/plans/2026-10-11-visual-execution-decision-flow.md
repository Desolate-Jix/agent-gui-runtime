# 视觉执行与 Decision 闭环实施计划 / Visual Execution and Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the integrated runtime tasks; use superpowers:subagent-driven-development only for explicitly bounded independent slices. Steps use checkbox (`- [x]`) syntax. Preserve the user's Sol ultra worker preference and reuse suitable existing workers. No nested delegation, commits or publication without a scoped instruction.

**Goal:** 从用户任务开始，让常规视觉执行在同一运行时自动推进，弹窗、目标可用性与语义安全交 Decision，异常可靠返回原 Main。 / Advance ordinary visual tasks in one runtime, using Decision for obstruction, feasibility and semantic safety, with reliable original-Main recovery.

**Architecture:** 复用现有 `task_plan`、`WorkflowRunner`、维护动作 API、Luna provider 和 `DecisionService`。以统一候选审核、明确输入回执和可恢复暂停连接现有模块；不另造执行器。默认建议定位后合并前置审核，并行场景预检作为独立对照选项。 / Reuse the existing runtime with unified candidate review, authoritative input receipts and recoverable waits. Recommend combined post-grounding review; optional parallel probing remains a separate comparison.

**Tech Stack:** Python, existing Windows capture/input/UIA adapters, httpx, MCP/JSONL, pytest, Markdown/Mermaid. No new production dependency is planned.

**Spec:** [修正流程图与设计 / Corrected flow and design](../specs/2026-10-11-visual-execution-decision-flow-design.md).

**Status:** **2026-10-12：零输入回执及现场代码缺陷已修、离线回归通过；三次实测点击地址栏后中断，最终为焦点Decision不确定，完整验收未完成 / Receipt and observed code defects repaired with passing offline checks; three trials stopped after address-bar clicks, the final one at uncertain focus Decision. Full acceptance remains incomplete.**

## 本轮实施记录 / Implementation checkpoint

2026-10-12最新补充：用户指定有点击标注的Decision帧仅上传标注整图，原图本地保留；新输入后Choice只核对规定文字。462项相关离线回归与4次正式provider固定截图重放通过，完整浏览器连续验收待进行。前序双图、predicate阈值测试保留为历史，Choice不按概率再次否决。 / Latest update: annotated frames upload only the marked full image, with originals retained locally; post-input Choice checks text only.462 offline checks and four production-provider retained-image replays passed; continuous-browser acceptance remains open. Earlier dual-view/predicate evidence is historical; Choice has no probability re-veto.

源码任务 1–7 已接入原维护运行时，最终离线结果和剩余限制以[本轮证据](../../verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md)为准。下方测试名是原计划的意图名称；实际命令、用例和 RED/GREEN 位于证据目录，不用名称相似代替验证。Task 8 已执行获准首步及同图只读诊断，完整连续验收和收益比较未完成。 / Tasks 1–7 are integrated into the existing runtime. The evidence record identifies actual tests and limits. Test names below express the original planned intent; concrete executed cases and failures are recorded separately. Task 8 includes an authorized first attempt and read-only diagnosis, without complete continuous acceptance.

2026-10-12修订：目标优先复核，最多一次额外 Decision；本次认证区域内继续变化不再要求整页静止，保护区及范围外变化仍拒绝，不跨动作缓存。已认证合并审核采用真实点击足迹，未配置Decision路线保留原语义。视觉字段仍只支持可精确核验的替换；取消、单次输入及身份绑定不变。 / Updated 2026-10-12: one target-focused relevance review permits continuing changes inside the authenticated region for this action, while retaining protected/outside-region checks and no cross-action cache. Combined approval uses the actual click footprint; no-Decision behavior is preserved. Exact-value replacement, cancellation, single dispatch and identity binding remain unchanged.

## Global Constraints

- 用户后来批准的同范围实测记录已保存；最新要求先审核旧规则，本次清理后只做离线验证。不提交或发布。 / Later scoped live trials are preserved; the latest instruction prioritizes rule review, so this cleanup uses offline validation without commits or publication.
- 普通执行以视觉定位为主；不强制安装学习组件，不把 UIA 整树扫描或学习检索加回每步前置流程。 / Ordinary execution is vision-first, without mandatory learning installation, full-tree UIA scans or per-step learning lookup.
- 复用原 Main、宿主、客户端、DecisionService、task_plan 和 WorkflowRunner；不建立第二套执行器。 / Reuse the original Main, host, client, DecisionService, task_plan and WorkflowRunner; do not create a second executor.
- 所有真实点击仍走维护的 gated action API；禁用原生 Codex Computer Use。 / All real clicks retain the maintained gated action API; native Codex Computer Use remains disabled.
- Decision 是条件判断服务；本地适配器组合条件，不假定上游新增工具调用、自由 JSON 或坐标生成能力。 / Decision evaluates predicates. Local composition does not assume new upstream tools, arbitrary JSON or grounding capabilities.
- 不静默更改冻结配置、阈值、付费上限或旧 task_plan.v1/v2 语义；英语默认、中文可切换。 / Preserve frozen configurations, thresholds, paid caps and old task_plan.v1/v2 semantics; English remains default with Chinese available.
- 新文档中英同步、UTF-8；保留既有未提交改动及首次失败证据。 / Keep new documentation bilingual and UTF-8, preserving unrelated edits and first-failure evidence.

## Review Focus

1. DOM 遮罩没有原生 popup handle：仍需判断，不能当作无遮挡。Task 2 覆盖。 / A DOM overlay lacks a native handle but still needs assessment; Task 2.
2. 模型等待期间仅广告动了与目标真的移动了必须区分。Task 3 覆盖。 / Distinguish unrelated animation from a moved target; Task 3.
3. 点击已执行、文字部分填入后超时：保留子回执，不从头重放。Task 4/5 覆盖。 / Preserve partial-input receipts without replay; Tasks 4/5.
4. 复用宿主的额度已耗尽或条件不在 allowlist：说明未调用原因，不能误称模型拒绝。Task 1 覆盖。 / Exhausted reused-session budget or disallowed predicates must be diagnosed as no call; Task 1.
5. Main 处理弹窗后原任务仍待完成，且用户可能取消：恢复不能复用旧坐标或晚到许可。Task 5/6 覆盖。 / Recovery after Main handling must honor fresh coordinates and cancellation; Tasks 5/6.

## 文件职责与顺序 / File ownership and order

| 阶段 / Phase | 主要文件 / Main files | 交付边界 / Deliverable |
| --- | --- | --- |
| P0.1 上下文和预算 / Context and budget | 新增 `app/execution/action_review.py`；现有 `decision_check.py`, `task_plan_review.py`, `app/judgment/service.py` | 统一审核绑定与总截止时间 / Unified review binding and deadline |
| P0.2 合并前置审核 / Unified precheck | `local_direct_step.py`, `popup_decision.py`, `app/api/action.py`, `app/core/window_manager.py` | DOM/原生场景都走同一次候选审核 / One candidate review across scene types |
| P0.3 新鲜度 / Freshness | 新增 `app/execution/target_freshness.py`；上述审核/动作入口 | 完整性与当前目标有效性分开 / Separate integrity and target freshness |
| P0.4 视觉输入 / Visual input | `input_sequence.py`, `app/core/local_text_focus.py`, `app/core/local_keyboard_target.py`；新增 `app/execution/visual_field_proof.py` | UIA 不可用时可验证的字段路径 / Verifiable fields without mandatory UIA |
| P0.5 恢复 / Recovery | `task_plan_backend.py`, `task_plan_verification.py`, `task_plan_review.py`, `task_plan_admission.py`, `app/learning_memory/workflow_runner.py` | 零输入暂停、未知输入对账、原 Main 恢复 / Correct intervention and reconciliation |
| P1.1 目标完成 / Completion | `task_plan_contract.py`, `task_plan_backend.py`, `scripts/execution_client.py`, `app/instant_mcp.py` | 新计划格式及真实完成条件 / New plan schema and goal completion |
| P1.2 可选并行 / Optional parallelism | `action_review.py`, `local_direct_step.py`, `app/judgment/profile.py` | 有预算、有认证的实验开关 / Bounded authenticated comparison option |
| P1.3 真实验收 / Acceptance | 现有 `scripts/execution_client.py`；新增 `docs/verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md` | 首败/复测、连续真实任务和调用/用时证据 / Real continuous-flow evidence |

`app/execution/` 为表中省略目录的默认前缀。源文件现已按分片实现，状态以本轮证据记录为准。P0 是一个紧耦合链路，按顺序集成；只并行委派明确独立的只读核对或测试分片。 / Unqualified filenames use app/execution/. Source slices are implemented; consult the current evidence record. Integrate P0 sequentially; delegate only bounded independent investigations/checks.

## 本地接口 / Local interfaces

以下均为本地接口，不声称上游 API 支持这些字段。实现时复用既有类型与序列化约定；不要重造截图、窗口或回执格式。 / These are local interfaces, not upstream API claims. Reuse existing capture/window/receipt formats.

```python
# 以下为本地接口摘要，实际可调用参数以源码为准。
ActionReviewEnvelope = dict
ActionAssessment = dict
DispatchProof = dict
FreshnessAssessment = dict
FieldProof = dict

def build_action_review(*, scope: str, plan: dict, step: dict, run_id: str,
    attempt_id: str, capture: dict, identity: dict, candidate: dict | None,
    action: dict, profile_sha256: str, deadline_ns: int) -> ActionReviewEnvelope: ...

def assess_candidate(service, *, envelope: ActionReviewEnvelope) -> ActionAssessment: ...

def assess_scene(service, *, envelope: ActionReviewEnvelope) -> ActionAssessment: ...

def check_target_freshness(*, before: dict, current: dict,
    candidate: dict, context_regions: list[dict]) -> FreshnessAssessment: ...

def build_visual_field_proof(*, phase: str, focus_receipt: dict,
    input_receipt: dict | None, frame: dict, assessment: dict,
    expected_field: dict, context: dict, value_reading=None, focus_snapshot=None) -> FieldProof: ...
```

`build_action_review` 产生 `schema=action_review.v1`，冻结 spec §4.1 的字段，并含 `scope=candidate|scene`、`remaining_plan`、`allowed_states` 和 `condition_snapshot`。scene 的 candidate 为 `None`；候选请求必须有 bbox/point。`ActionAssessment` 引用 envelope SHA、原 service result 和认证状态，disposition 仅 `pass|review|unavailable`，始终 `authorizes_action=False`。`DispatchProof` 引用维护入口的真实输入状态与子回执，不能由调用方自称零输入。`FreshnessAssessment.status=valid|changed|unknown`；`FieldProof` 绑定 focus receipt、field、window、capture、期望文本和已认证证据，不能由任意 dict 绕过核心 issuer。 / Envelope/result bindings distinguish scene from candidate scope. Assessment never grants input authority. Dispatch and field proofs must originate from maintained authenticated boundaries, not caller assertions.

新 interface 的 scope 应由构造器明确验证；`assess_scene` 只接受无候选的 scene envelope，`assess_candidate` 只接受完整候选。deadline 为进程内单调时间，不作为跨进程持久值；重启不得重新兑现旧许可。 / Enforce scope in constructors and assessment entrypoints. Monotonic deadlines are process-local; restart cannot revive persisted authority.

字段证明的 `phase=focus|value` 必须与证据时序一致：focus 证明来自点击之后，input_receipt 为 None，不能证明尚未输入的值；value 证明来自填写之后，必须带实际 input_receipt 和精确期望文本。二者不能相互替代。 / Field proof phase is temporal: focus evidence follows the focus click with no typing receipt; value evidence follows typing and requires its receipt plus expected text. They are not interchangeable.

## Task 1 — P0：冻结上下文、实际可用性与共享预算 / Context and shared budget

**Files:** Create `app/execution/action_review.py`; modify `app/execution/decision_check.py`, `app/execution/task_plan_review.py`, `app/judgment/service.py`; create `tests/test_action_review_contract.py`.

**Interfaces:** Produces `build_action_review` and scope-specific authenticated assessments; extends existing `_evaluate`/`DecisionService.evaluate` with optional remaining-deadline input while preserving legacy callers.

- [x] 写 `test_candidate_binds_full_task_and_remaining_plan`、`test_scene_cannot_be_adopted_as_candidate`、`test_preflight_reports_allowlist_and_host_budget`；分别断言实际任务/余下步骤被冻结、scope 不能升级、零网络派发有独立原因。 / Write binding and no-dispatch diagnostics tests.
- [x] 运行上述新用例，确认因新合同尚不存在失败；保留失败原因。 / Confirm the intended initial failure.
- [x] 实现 envelope、构造校验与一次任务级 preflight；额度继续在实际调用时原子扣减，不自动增加上限或重试。 / Implement validated envelopes/preflight with atomic per-call debits.
- [x] 给 Luna、Decision 与重采调用传剩余总预算；写 `test_combined_deadline_is_not_reset`、`test_cancelled_or_late_result_is_not_adopted`，验证晚返不产生许可。 / Propagate remaining time, reject stale/late results.
- [x] 运行 `python -X utf8 -m pytest tests/test_action_review_contract.py tests/test_execution_decision_check.py tests/test_decision_http_deadline.py -q`，预期全部通过；同步 `docs/development/DECISION_API.md` 的绑定与未调用原因。 / Verify and document.

## Task 2 — P0：一次候选审核覆盖目标、弹窗和安全 / Combined candidate review

**Files:** Modify `app/execution/action_review.py`, `app/execution/local_direct_step.py`, `app/execution/popup_decision.py`, `app/api/action.py`, `app/core/window_manager.py`, `configs/decision-profile.adaptive.example.json`; create `tests/test_action_review_route.py`; extend `tests/test_popup_decision_route.py`.

**Interfaces:** Consumes Task 1 envelope/assessment. `assess_candidate` composes existing Decision predicates into one request. Existing owner-thread guard consumes only the authenticated result for the exact original action.

- [x] 写 `test_unrelated_popup_does_not_refuse_address_bar`、`test_dom_overlay_enters_same_review`、`test_actual_point_occlusion_still_blocks`；模拟原生与 DOM 场景，断言一次前置请求、原动作保持、遮挡点零输入。 / Test semantic popup handling and objective occlusion.
- [x] 确认新用例首败；实现统一条件与现有 provider 契约映射，不添加第二个 popup Decision 调用。更新已有显式 before_action 检查的去重规则：条件/候选/证据完全相同才可复用。 / Implement one combined call and exact-scope deduplication.
- [x] 以代码定义的 `CANDIDATE_CONDITION` 确切条件描述“指定原动作命中预期可见目标、符合任务及允许动作类别、无需处理弹窗或其他介入即可安全继续”；映射现有 `condition_met`、`unsafe_effect`、`needs_agent_review`，更新新配置示例的明确许可。未批准该条件的冻结 profile 仍返回 unavailable，不自动改 allowlist 或前置阈值。 / Map a fixed local candidate-feasibility condition to existing predicates and explicit new-profile permission, preserving frozen profiles.
- [x] 将原生窗口检测保留为事实采集和物理派发检查；缺 handle 的 DOM 遮罩仍进入视觉审核。Main 接管携带具体拒绝理由而非笼统弹窗错误。 / Preserve native facts without blanket refusal.
- [x] 写 `test_worker_cannot_issue_dispatch_guard`、`test_wrong_candidate_or_profile_rejects_adoption`；验证 thread、candidate、profile 绑定。 / Pin authority and authentication boundaries.
- [x] 运行 `python -X utf8 -m pytest tests/test_action_review_route.py tests/test_popup_decision_route.py tests/test_nonmodal_popup_parent_click.py tests/test_point_visibility_no_dispatch.py -q`；预期通过，同步 `docs/development/DECISION_API.md`。 / Verify and document.

## Task 3 — P0：只因相关变化作废候选 / Relevant freshness

**Files:** Create `app/execution/target_freshness.py`, `tests/test_target_freshness.py`; modify `app/execution/action_review.py`, `app/execution/popup_decision.py` and the current pre-dispatch freshness boundary in `app/api/action.py`.

**Interfaces:** Produces `check_target_freshness`; consumes authenticated original/current capture metadata. Reuses existing maintained image evidence helpers, without a new vision executor.

- [x] 写 `test_unrelated_animation_preserves_candidate`、`test_target_move_invalidates_candidate`、`test_context_text_change_invalidates_candidate`、`test_new_occlusion_invalidates_candidate`、`test_modified_original_artifact_rejected`；使用新合成帧证明完整性和新鲜度分别生效。 / Test relevant change versus artifact tampering.
- [x] 先确认新用例失败，再实现相关区域/锚点核验；没有足够证据的排除区域返回 unknown，不凭固定网站坐标排除广告。 / Implement conservative evidence-based regions, not site-specific masks.
- [x] 实际实现有界相关性复核：最多一次额外 Decision；本次认证无关区域内继续变化可通过，目标或范围外变化交 Main。未增加自动 Luna 重定位；零输入经 Main 新 attempt。晚返不能覆盖当前候选。 / Implement one bounded relevance reassessment with same-action irrelevant-region tolerance; protected/outside changes still require Main, without automatic re-grounding. Proven zero-input may resume as a new attempt.
- [x] 运行 `python -X utf8 -m pytest tests/test_target_freshness.py tests/test_popup_decision.py tests/test_action_review_route.py -q`；预期通过，文档分别解释完整性与新鲜度。 / Verify and document.

## Task 4 — P0：闭合视觉输入的焦点和内容证明 / Visual field proof

**Files:** Create `app/execution/visual_field_proof.py`, `tests/test_visual_field_proof.py`; modify `app/execution/input_sequence.py`, `app/core/local_text_focus.py`, `app/core/local_keyboard_target.py`; extend `tests/test_input_sequence_focus_partial.py`.

**Interfaces:** Produces `build_visual_field_proof`; extends existing local field capability with an explicit `evidence_kind=visual` variant. Reuses `assess_candidate` context/identity authentication and current gated focus/type/Enter boundaries.

- [x] 写 `test_missing_uia_uses_proven_visual_focus`、`test_preclick_pass_is_not_postclick_focus`、`test_ambiguous_focus_types_nothing`；有界 UIA 可用时仍保持原证明，缺失时只接受受支持视觉证明。 / Test genuine post-focus evidence and no blind typing.
- [x] 确认首败后实现：焦点点击回执 → 新帧的字段焦点证明 → 填写 → 新帧或有界字段读取核验值 → 原有限定的搜索 Enter。可把同一时刻的字段/值条件合并，但不得把不同时间的事实预先证明。 / Implement ordered field evidence without pre-certifying future focus or value.
- [x] 写 `test_partial_text_timeout_never_retypes`、`test_focus_change_before_type_blocks`、`test_nonsearch_enter_not_promoted`、`test_unreadable_value_requires_review`；保留中文 UTF-8 与精确文本语义，视觉无法精确核验则 Main。 / Test partial input, changed focus, action taxonomy and unreadable text.
- [x] 运行 `python -X utf8 -m pytest tests/test_visual_field_proof.py tests/test_input_sequence_focus_partial.py tests/test_local_text_focus_revalidate.py tests/test_local_keyboard_target.py -q`；预期通过，同步 `docs/verification/EXECUTION_INPUT_SEQUENCE.md`。 / Verify and document limitations and extra calls.

## Task 5 — P0：零输入暂停与原 Main 恢复 / Intervention and recovery

**Files:** Modify `app/execution/task_plan_backend.py`, `app/execution/task_plan_verification.py`, `app/execution/task_plan_review.py`, `app/execution/task_plan_admission.py`, `app/learning_memory/workflow_runner.py`, `scripts/execution_client.py`, `app/instant_mcp.py`; create `tests/test_task_plan_pre_dispatch_review.py`; extend `tests/test_task_plan_queued_cancel.py`.

**Interfaces:** Add `TaskPlanBackend.record_pre_dispatch_block(run_id, request_id, execution_request_id, proof: DispatchProof, assessment: ActionAssessment) -> dict` and `resume_pre_dispatch(run_id, request_id, wait_id, review: dict) -> dict`. Reuse original review packet authentication, idempotency ledger and runner ownership. Known-completed effects use existing settlement; unknown/partial results retain original tickets.

启动接口新增显式 `recovery_policy=legacy|intervention_v1`，冻结在运行元数据及审核绑定中。旧 v1/v2 省略时为 legacy；本 Task 的暂停/恢复只对 intervention_v1 生效。Task 6 的 v3 默认选 intervention_v1。实际通过 `permit_recovery` / `consume_recovery` 及原回执结算路径签发和消费服务内部一次性许可，不接受调用方自制 token。 / Add an explicit frozen recovery policy with legacy defaults for existing plan versions and intervention defaults for v3. Issue and settle exact recovery actions through internal one-use authority.

- [x] 写 `test_zero_dispatch_block_is_resumable`、`test_unknown_dispatch_cannot_enter_zero_input_resume`、`test_completed_prefix_not_replayed`；只有可信零输入可进入同一步新 attempt。 / Pin recovery categories.
- [x] 确认首败后扩展现有 packet/wait，不另建 runner；恢复后重新截图定位审核。Main 若需处理弹窗，恢复动作有独立授权、票据和当前窗口核验，不能混进原业务动作回执。 / Implement through existing runner with distinct recovery receipts.
- [x] 写 `test_legacy_zero_dispatch_retains_old_settlement` 与 `test_intervention_policy_pinned_at_start`；把模式从 Client/MCP start 接入后端，旧宿主不支持时明确拒绝，不静默丢失参数。 / Pin the explicit compatibility boundary end to end.
- [x] 写 `test_recovery_action_admitted_only_for_bound_wait`、`test_recovery_receipt_required_before_resume`、`test_recovery_permit_cannot_override_cancel`；扩展现有 admission 只放行精确绑定的恢复输入，其他命令仍拒绝。 / Add narrow recovery admission, not an active-plan bypass.
- [x] 写 `test_resume_uses_new_attempt_execution_id` 与 `test_repeated_resume_request_is_idempotent`；intervention_v1 的执行 ID 绑定 run/step/attempt，legacy 保持旧算法。旧零输入票据保留为已结清拒绝，原 wait 审核通过后原子建立一个新 attempt；重复恢复请求只读回该 attempt。 / Bind intervention execution IDs to attempts and make resume atomic/idempotent, preserving the rejected ticket and legacy IDs.
- [x] 写 `test_focus_only_receipt_stays_partial`：focus 已执行、type 未开始时必须暂停，不能进入 zero-dispatch resume、完整成功或自动 successor；第一版不实现部分输入自动续跑。 / Explicitly exclude automatic partial-input continuation.
- [x] 写 `test_cancel_wins_over_late_review`、`test_repeated_obstruction_pauses_after_one_recovery`、`test_waiting_user_does_not_cycle_main`；按 spec §5 覆盖用户等待、重复阻挡及取消。 / Bound recovery and respect user state.
- [x] 写 `test_successor_requires_settled_parent_and_quiet_queue`，保留未知动作及已完成子步骤；review 不能使未知自动成为未执行。 / Preserve successor and unknown-input invariants.
- [x] 运行 `python -X utf8 -m pytest tests/test_task_plan_pre_dispatch_review.py tests/test_task_plan_queued_cancel.py tests/test_task_plan_start_admission.py tests/test_workflow_runner.py -q`；预期通过，同步 `docs/development/TASK_PLAN.md`。 / Verify and document.

## Task 6 — P1：最终目标闭合与公开入口 / Final goal and public entrypoint

**Files:** Modify `app/execution/task_plan_contract.py`, `app/execution/task_plan_backend.py`, `app/execution/task_plan_review.py`, `scripts/execution_client.py`, `app/instant_mcp.py`; extend `tests/test_task_plan_contract.py`; create `tests/test_task_plan_goal_completion.py`.

**Interfaces:** `task_plan.v3` adds exact top-level fields `goal: str` and `completion: {step_id: str, verification: dict}` to the existing shape. `step_id` must name the final step; `verification` reuses the existing maintained semantic/native/temporal verification shape, validated in v3 using v2-compatible rules and an immutable snapshot SHA. Reuse the final step assessment when it proves that same condition; otherwise perform a read-only review, never an extra action. No new arbitrary predicate/condition object is accepted.

- [x] 写 `test_v3_requires_observable_goal_completion`、`test_old_plan_versions_retain_semantics`、`test_last_click_success_is_not_goal_success`；新格式缺 goal/completion 拒绝启动，旧格式冻结含义不变。 / Test explicit completion and compatibility.
- [x] 确认首败后扩展 validator、client/MCP 入参、来源哈希、review context、completion adoption 和状态查询；如后端尚不支持 v3，客户端明确报不兼容，不降级伪装成 v2。 / Wire the new schema end to end with explicit compatibility errors.
- [x] 写 `test_same_final_evidence_avoids_extra_api`、`test_final_review_is_readonly`、`test_cancel_beats_final_success`；后验条件绑定实际目标，三图变化不能冒充特定视频成功。 / Reuse matching evidence and preserve goal/cancel semantics.
- [x] 运行 `python -X utf8 -m pytest tests/test_task_plan_contract.py tests/test_task_plan_goal_completion.py tests/test_task_plan_review_context.py tests/test_execution_client.py -q`；预期通过，同步 README 与 `docs/development/TASK_PLAN.md`，标为源码状态。 / Verify and synchronize public documentation without claiming release.

## Task 7 — P1：可选并行预检 / Optional parallel scene probe

**Files:** Modify `app/execution/action_review.py`, `app/execution/local_direct_step.py`, `app/judgment/profile.py`; create `tests/test_parallel_scene_probe.py`.

**Interfaces:** Proposed new profile field `scene_precheck=off|parallel`, default `off` for new profiles. `assess_scene` accepts scene scope only; the original thread joins data and still requires candidate assessment. Legacy profile serialization/hash must remain stable when the field is absent.

- [x] 写 `test_parallel_scene_pass_never_authorizes_candidate`、`test_same_frame_required_at_join`、`test_early_block_cancels_grounding`、`test_extra_probe_debits_budget`；证明 B 不把场景通过升级为坐标通过。 / Pin scope, joining, cancellation and cost.
- [x] 确认首败后仅增加数据计算并行，不跨线程使用 ContextVar/guard，不重复初始化 provider/宿主。API 错误/超时明确记录；B 的不确定结果不凭空证明有弹窗。 / Implement data-only parallelism with explicit failures.
- [x] 运行 `python -X utf8 -m pytest tests/test_parallel_scene_probe.py tests/test_action_review_contract.py tests/test_action_review_route.py -q`；预期通过。开关仍为 off，是否改变默认由 Task 8 的真实对照决定。 / Verify; retain off pending measured benefit.

## Task 8 — P1：真实流程、收益对照和交付判断 / Real acceptance and benefit

**Files:** Use `scripts/execution_client.py`; update `docs/verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md` with each source/live checkpoint. Update affected README, local CURRENT_STATE/PROJECT_SUMMARY/ARCHITECTURE/NEXT_STEPS, and any existing bilingual runtime graph together.

**Interfaces:** Consume the frozen Task 1–7 candidate; no separate benchmark executor. Trace spans: `task_received`, `plan_ready`, `session_ready`, `capture`, `grounding`, `scene_review`, `candidate_review`, `freshness`, `dispatch`, `result_review`, `main_wait`, `task_completed`, with actual request IDs and input receipts.

- [x] 先完成相关离线单元/契约及公开 Client → maintained host → 原输入边界的隔离集成；模拟 provider 必须明确标注，不能代表真实准确性。 / Complete relevant offline and public-path integration first.
- [x] 按后续授权执行首步及只读诊断并保留首败、取消和清理证据；累计10请求，无真实输入。 / Run the approved first attempt and read-only diagnosis; retain first failure and cleanup, ten requests and zero input.
- [ ] 用新配置完成原失败任务 Google → java → 第一个普通结果及收尾；新before=0.80已离线通过，尚未实机采用。 / Complete the original flow with the new profile;0.80 is offline-verified, not live-accepted.
- [ ] 完成同一会话连续场景：正常导航、无关弹窗、实际遮挡、动态广告、目标移动、字段焦点变化、加载、Main 处理恢复、用户取消；API 缺失/失败/额度耗尽及未知回执用隔离故障注入补齐，不能危险地制造真实输入不确定性。 / Cover realistic continuity plus safely injected failure paths.
- [ ] 冻结模型/profile/窗口策略，对 A 与 B 做交错对照；先每路线 10 个匹配任务作为试测，报告样本数、全部首败和原始耗时。样本不足只报描述值，不宣称总体准确率；p95 保留样本量说明。 / Run interleaved frozen comparisons, initially ten matched tasks per route, with explicit small-sample limits.
- [ ] 记录用户收到请求至首次有效动作、总完成、Main/tool 等待、Luna/Decision 时间、调用数/usage、首次成功、错误放行/误拒与最终误报；不把只测 API 的秒数冒充体感用时。 / Measure user-visible end-to-end latency and accuracy, not API time alone.
- [ ] 遇到错目标、重复输入、取消后新输入或错误宣告完成即停止候选验收，先修共用合同并回归；单次通过不代替连续通过。 / Stop acceptance on violated input/completion invariants, repair the common contract and rerun.
- [ ] Main 完成单项、连续流程和收尾后，才安排 Sol ultra 对同一冻结候选独立验收。是否打包/安装/发布另作交付决定，不由本计划自动触发。 / Independent acceptance follows Main's complete coverage; packaging/publication are separate decisions.

## 完成检查 / Completion review

计划顺序是 **上下文/预算 → 合并审核 → 新鲜度 → 视觉输入 → 可恢复暂停 → 最终完成 → 并行对照 → 真实连续验收**。P0 未闭合前不扩大实机任务，不用学习索引或 UI 美化替代执行链修复。 / Sequence: context/budget → combined review → freshness → visual input → recovery → goal completion → optional parallel comparison → continuous real acceptance. Do not substitute learning indexing or UI polish for closing P0.

本轮已执行源码与离线检查，首次失败与修复记录保存在本轮目录。此前 218 项是历史证据，不与本轮重复累加；真实准确率及完整连续流程仍未通过；单次API时长不代表整任务性能。 / Source and offline checks preserve first failures. Earlier counts are historical, not added again; isolated API timings do not establish end-to-end performance or complete live acceptance.
