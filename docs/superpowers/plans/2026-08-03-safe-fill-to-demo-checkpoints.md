# Safe Fill To Demo Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从当前已完成的表单 inventory 与答案策略出发，小步验证通用安全填写、动态问题、多步骤状态机和首条真实 no-submit 流程，最终形成可复跑、可审查的技术 Demo。

**Architecture:** 通用能力继续落在 Agent、Operation、Gate、Trace 和状态机边界中，SEEK 只作为第一个真实网站适配器。每个真实动作都使用当前截图重新定位并经过 Gate；学习资产、PathGraph 和答案策略只提供决策证据，不提供执行授权。

**Tech Stack:** Python 3.11、FastAPI、pytest、Windows GUI Operation、OCR/UIA/VISTA、HTML fixture、原生 JavaScript 面板。

## Global Constraints

- 不点击最终 `Submit`、`Send`、`Complete`、`Confirm` 或支付动作。
- 不自动回答敏感问题；未知、薪资、签证、搬迁和歧义问题必须暂停人工确认。
- 不在 Trace、报告、stdout 或失败详情中保存原始 PII，只保存字段名、hash、length、redacted preview 和 evidence reference。
- fixture 结果不能表述为 live 稳定性；单次 live 结果不能表述为端到端可靠性。
- 每个动作必须分开报告 policy、grounding、Gate、dispatch、effect 和 post-observe verification。
- 任何 checkpoint 失败时停止扩展，先修复可复用 runtime invariant 并补回归测试。

---

### Checkpoint 9A: 文本填写执行契约

**Files:**
- Create: `app/operation/form_fill_executor.py`
- Create: `tests/test_form_fill_executor.py`

**Interfaces:**
- Consumes: `form_action_gate_decision_v1`、当前 `recognition_plan_v1`、当前 capture id、审核值引用。
- Produces: `form_fill_action_request_v1` 和不含原始值的 `form_fill_action_result_v1`。

- [x] 写失败测试：拒绝 policy 未允许、capture 不一致、point 不在 bbox、`clear_existing=false`、final action 和缺少真实 Action Gate 的请求。
- [x] 运行 `uv run pytest tests/test_form_fill_executor.py -q`，确认测试因实现缺失而失败。
- [x] 实现一次文本输入所需的最小验证和 dispatch 边界；返回值只含 hash、length、redacted preview。
- [x] 重跑测试并执行 `uv run python -m py_compile app\operation\form_fill_executor.py`。

**Checkpoint pass:** 单个文本动作只有在答案策略、当前定位和真实动作 Gate 同时允许时才可 dispatch；尚不声称页面值已改变。

---

### Checkpoint 9B: 文本填写效果验证

**Files:**
- Modify: `app/operation/form_fill_executor.py`
- Modify: `tests/test_form_fill_executor.py`

**Interfaces:**
- Consumes: 批准值 hash/length 和 post-observe 当前字段值。
- Produces: `form_fill_effect_verification_v1`。

- [x] 写 hash/length 一致时 effect pass 的测试。
- [x] 写 dispatch 成功但字段未变化、值被截断、读到错误字段和 capture 过期的失败测试。
- [x] 实现 `verify_form_text_fill_effect(...)`，明确区分 `dispatch_success` 与 `fill_effect_success`。
- [x] 运行 focused tests 和相邻 Gate/runtime contracts。

**Checkpoint pass:** “发出了输入”不能再被包装成“填写成功”。

**Evidence (2026-08-03):** `tests/test_form_fill_executor.py` 先因缺少执行器和 effect verifier 失败，随后通过 `12 passed`；与 form policy、runtime contracts 和 layer facade 的相邻回归通过 `46 passed`。当前只验证公共契约和注入 dispatcher，没有 live form filling。

---

### Checkpoint 9C: 本地真实文本字段闭环

**Files:**
- Create: `tests/fixtures/general_form_live_site/index.html`
- Create: `scripts/run_general_form_fixture_smoke.py`
- Create: `tests/test_general_form_fixture_smoke.py`

**Interfaces:**
- Produces: Agent -> Gate -> Operation -> Trace -> observe 的单字段真实 fixture 证据。

- [x] 建立只含普通姓名输入框、可读取状态区和最终提交诱饵按钮的本地页面。
- [x] 写 smoke 测试，要求输入前后截图、current capture、Gate、dispatch、effect 和 Trace 路径齐全。
- [x] 通过 gated action API 真实填写一个无敏感测试值，随后重新 observe；不点击提交。
- [x] 检查报告和 Trace 不含测试原始值。

**Checkpoint pass:** `live_fixture_fill_attempted=1`、`fill_effect_success=true`、`submit_clicks=0`。

**Evidence (2026-08-03):** 真实本地 Edge fixture 运行写入 `logs/smoke/general_form_fixture_cp9c_next2/general_form_fixture_smoke_report.json`，结果为 `status=pass`、`live_fixture_fill_attempted=1`、`fill_effect_success=true`、`submit_clicks=0`。首次运行暴露 Edge renderer accessibility 未开启，修复后 UIA 唯一召回 `First name` 编辑框；第二次运行暴露 `pre_click_decision_v1` 与 `operation_context.semantic_action` 的投影缺口，修复后完整 Gate/Operation/Trace/post-observe 闭环通过。focused suite 为 `8 passed`，相邻表单测试为 `46 passed`，语法检查通过。报告、RecognitionPlan Trace 和 type-text Trace 均未出现原始测试值。这是受控 fixture 的真实 GUI 输入证据，不是 live ATS safe-fill 可靠性。

---

### Checkpoint 10A: 下拉框单动作

**Files:**
- Modify: `app/operation/form_fill_executor.py`
- Modify: `app/operation/form_fill_verification.py`
- Modify: `tests/fixtures/general_form_live_site/index.html`
- Modify: `tests/test_form_fill_executor.py`

- [x] 写 `open dropdown -> re-observe -> select option -> re-observe` 测试。
- [x] 写重复标签、错误 question ownership 和 disabled option 的拒绝测试。
- [x] 实现 `select_option` 的单步推进，不在旧截图上连续点两次。
- [x] 在本地 fixture 真实选择一个选项并验证 selected 状态。

**Checkpoint pass:** 下拉选择有当前证据和效果验证，歧义时安全停止。

**Evidence (2026-08-03):** 受控本地 Edge fixture 运行写入 `logs/smoke/general_form_dropdown_cp10a_final/general_form_dropdown_fixture_smoke_report.json`，结果为 `status=pass`、`dropdown_open_attempted=1`、`option_select_attempted=1`、`selection_effect_success=true`、`submit_clicks=0`。打开与选择分别通过当前截图定位和 Gate，两个动作之间以及选择后均重新观察。focused 与相邻表单验证共 `57 passed`。报告只保留答案 hash、长度和脱敏预览；动作 Trace 可保留当前页面可见的选项标签作为定位证据。本次覆盖页面内、可稳定截图的 ARIA combobox/listbox；Chromium 原生 `<select>` 的瞬态弹层尚未满足同一证据契约，不计为已支持。这是 fixture-only 真实 GUI 证据，不是 live ATS safe-fill、完整表单或 final-submit 覆盖。

---

### Checkpoint 10B: 单选与复选

**Files:**
- Modify: `app/operation/form_fill_executor.py`
- Modify: `app/operation/form_fill_verification.py`
- Modify: `tests/fixtures/general_form_live_site/index.html`
- Modify: `tests/test_form_fill_verification.py`

- [x] 写 radio、checkbox、already-selected、disabled 和重复标签测试。
- [x] 实现 `select_radio` 与 `toggle_checkbox`，每个动作后重新读取 checked 状态。
- [x] 在本地 fixture 分别执行一次低风险 radio 和 checkbox。
- [x] 运行文本、下拉、单选和复选全部 focused tests。

**Checkpoint pass:** 三类选择控件均可单步验证，没有批量盲填。

**Evidence (2026-08-03):** 受控本地 Edge fixture 运行写入 `logs/smoke/general_form_choice_cp10b/general_form_choice_fixture_smoke_report.json`，结果为 `status=pass`、`radio_select_attempted=1`、`radio_effect_success=true`、`checkbox_toggle_attempted=1`、`checkbox_effect_success=true`、`already_selected_no_dispatch=true`、`submit_clicks=0`。单选与复选分别经过当前截图定位、Gate、真实低风险点击和重新观察；已经选中的 radio 不再重复 dispatch。focused 与相邻表单验证共 `78 passed`，相关 Python 模块编译通过。报告只保存选择值 hash 和长度；这是 fixture-only 真实 GUI 证据，不是 live ATS safe-fill、完整表单可靠性或 final-submit 覆盖。

---

### Checkpoint 11A: 动态问题语义归一化

**Files:**
- Create: `app/agent/form_question_understanding.py`
- Create: `tests/test_form_question_understanding.py`

**Interfaces:**
- Produces: `normalized_question_intent_v1`，包含 intent、polarity、risk、confidence 和 evidence。

- [x] 覆盖 `right to work`、`require sponsorship`、`work without sponsorship` 的同义、否定和反向极性测试。
- [x] 覆盖薪资、搬迁、犯罪史、健康和未知开放题，禁止靠关键词相似度直接自动回答。
- [x] 实现语义归一化；低置信度、否定冲突或时序矛盾 evidence 进入 `needs_user_review`。
- [x] 运行 focused tests。

**Checkpoint pass:** 问题文字变化不会导致反向回答；未知问题不猜。

**Evidence (2026-08-03):** `normalized_question_intent_v1` 已接入 `form_answer_decision_v1`。TDD 覆盖正向工作权利、反向担保需求、显式否定担保需求、当前/未来担保冲突、薪资、搬迁、签证、犯罪史、健康和未知开放题。聚焦测试为 `37 passed`；相邻表单、PII、inventory、policy 和 final-submit 安全回归为 `130 passed`；相关模块编译与 scoped diff check 通过。应用内 ChatGPT 桥返回空 tab 列表，因此外部语义复核未覆盖。没有模型调用、live ATS、live fill、点击或 submit；该产物不是执行授权。

---

### Checkpoint 11B: 人工确认与可复用答案记忆

**Files:**
- Create: `app/agent/form_answer_policy_memory.py`
- Modify: `app/agent/reviewed_interface_memory.py`
- Create: `tests/test_form_answer_policy_memory.py`

**Interfaces:**
- Produces reviewed scopes: `one_time`、`workflow_class`、`site`、`global_profile`。

- [x] 写人工批准、人工否决、语义极性变化和过期 evidence 测试。
- [x] 保存 intent、scope、答案引用和 evidence hash，不保存坐标或原始 PII。
- [x] 证明人工修正后，同义问题可复用；反向问题仍需重新判断。
- [x] 运行 focused tests 和 PII audit。

**Checkpoint pass:** 已知问题可使用经审核策略，未知或语义变化的问题暂停。

**Evidence (2026-08-03):** `FormAnswerPolicyMemoryStore` 已实现 `one_time`、`workflow_class`、`site` 和 `global_profile` 四种审核 scope，只持久化 intent、polarity、审核决定、opaque answer reference、evidence SHA-256 与有效期。人工否决、反向极性、过期 evidence、未知 intent 和 scope 不匹配均 fail closed；同义且同极性问题才可暴露经审核的答案引用。focused 验证为 `11 passed`，本次相邻语义、planner、Gate 与 reviewed-interface-memory 回归为 `55 passed`；测试同时断言持久化产物不含原始 PII、bbox、click point 或 raw value。该记忆仍为非授权 Agent 证据，不允许绕过当前 inventory、定位、Policy Gate 或 Action Gate，也没有执行 live ATS、fill、click 或 submit。

---

### Checkpoint 12A: 多步骤 fixture 状态机

**Files:**
- Create: `app/agent/form_workflow_controller.py`
- Modify: `app/agent/continuous_task_session.py`
- Create: `tests/test_form_workflow_controller.py`

**Interfaces:**
- Produces one action per turn: `fill_field`、`select_option`、`continue_next_step`、`request_user_review` 或 `safe_stop`。

- [x] 写两页表单、人工暂停、Continue、登录阻断、错误 surface 和 verification failure 测试。
- [x] 实现每轮只执行一个动作；Continue 后 capture、inventory 和定位全部作废并重建。
- [x] 运行 controller 与 continuous session tests。

**Checkpoint pass:** 状态机不假定问题数量和顺序，不复用旧步骤坐标。

---

### Checkpoint 12B: 最终审核页安全停止

**Files:**
- Modify: `tests/fixtures/general_form_live_site/index.html`
- Modify: `tests/test_form_workflow_controller.py`
- Modify: `tests/test_final_submit_guard_fixtures.py`

- [x] 在 fixture 第二页加入 `Review and submit`、`Submit application`、`Send` 和 `Complete` 变体。
- [x] 断言 final action 可见时 controller 只返回 `safe_stop`。
- [x] 断言 `unsafe_prevented=true`、`real_clicks=0`、`submit_clicks=0`。
- [x] 运行 final-submit fixture suite。

**Checkpoint pass:** 本地多步骤表单到最终审核页后硬停止。

**Evidence (2026-08-03):** 本地 fixture 现在显式包含 `questions -> review` 两阶段，最终审核页覆盖四类 final-action 文案，并保留 `#finalSubmit` 兼容定位。controller 对四类文案均返回 `safe_stop / final_submit_visible`，`unsafe_prevented=true`，不生成 Operation 请求；fixture 计数保持 `real-clicks=0 submit-clicks=0`。focused 验证 `22 passed`，相邻表单/会话回归 `141 passed`，全仓回归 `2525 passed, 1 skipped`，相关 Python 编译通过。这是 fixture-only 安全证据，不是 live ATS、live safe fill、真实最终审核或提交覆盖。

---

### Checkpoint 13: 面板技术演练

**Files:**
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/interface_workflow_graph.js`
- Modify: `tests/js/learning_workflow_review.test.cjs`
- Modify: `tests/js/interface_workflow_graph.test.cjs`

- [x] 从现有软件流程选择起点并显示当前带框图。
- [x] 显示 Agent 决策、Gate、dispatch、effect、post-observe、Trace 和 safe-stop 原因。
- [x] 人工确认后继续同一 session；保存修正后立即刷新证据。
- [x] 隐藏旧 benchmark、原始 JSON 和无关诊断，保留按需展开 Trace。
- [x] 跑 JS tests、panel route tests，并完成一次真实面板可视化排练。

**Checkpoint pass:** 不读 JSON 也能判断当前在哪一步、为什么继续或停止；面板不显示旧证据。

**CP13A evidence (2026-08-03):** 已实现 selected-node 单步审计投影，并保证证据源/节点切换时审计与带框图使用同一个 current view。无匹配运行证据时明确显示 `not_run`，不会继承其他节点结果。保存流程时保留语义审计、移除历史点击坐标并维持 display-only。验证为 JS `25 passed`、目标 panel routes `19 passed`、workflow review persistence `28 passed`，本地面板 smoke 已看到路径图、当前带框证据和 `not run` 审计。尚未完成带 recorded runtime report 的完整手工流程，也未验证人工确认后同 session 继续，因此 CP13 整体仍未通过。

**CP13B evidence (2026-08-03):** 已修正真实 `navigation_reading_controller_report_v1` 直接 step 字段的投影，保存后重新从流程库加载会保留语义审计、移除点击坐标、恢复原选中节点并刷新当前证据。同 session confirmation 和 navigation controller 的自动化回归为 `23 passed`；JS 为 `26 passed`，workflow review + panel route 为 `155 passed`。系统 Edge 在真实面板完成 recorded / unvisited 节点切换和保存复载排练，报告位于 `logs/smoke/cp13b_panel_recorded_runtime/cp13b_panel_recorded_runtime_smoke_report.json`。排练拦截保存和读取请求，没有修改持久用户资产，也没有进入 live ATS、执行 live fill、点击目标软件或触发 submit。CP13 面板技术验收通过，但不代表 live runtime 可靠性。

---

### Checkpoint 14: 真实网站只读 inventory

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Create: `docs/SEEK_NO_SUBMIT_UAT.md`

- [ ] 运行 GPU、模型、窗口、capture、no-submit 和 Trace preflight。
- [ ] 进入一个 Quick Apply 表单，只读取 inventory 和答案策略，不填写。
- [ ] 人工核对允许字段、未知问题、敏感问题、file upload 和 final action 分类。
- [ ] 修复 common runtime contract 后才允许重跑；SEEK adapter 只转换网站 evidence。

**Checkpoint pass:** live inventory 可人工审核，`live_fill_attempted=0`、`submit_clicks=0`。

**CP14 implementation checkpoint (2026-08-03):** `seek_debug_step_runner.py` 和 `seek_speed_demo_runner.py` 已增加独立 `--read-only-inventory` 路径。该路径只观察一次当前表单、生成字段/问题/最终动作与脱敏回答策略报告，然后以 `next_allowed_steps=["capture"]` 停止；不会调用 safe fill、employer answer fill 或 Continue。checkpoint 的 `human_review` 投影会把普通字段、需复核问题、敏感问题、不支持上传和最终动作分开显示，不包含原始答案，也不构成填写授权。`--cp14-live-uat` 还会在 Apply 入口点击前生成 fail-closed `seek_cp14_apply_preflight_v1`，检查 Runtime health、共享 GPU resource preflight、Locate model service、continuous session、只读模式、显式批准、窗口绑定、新截图、Trace 和 Agent match decision；任一失败即在点击前停止。离线成功路径还固定了 Apply 入口一次、只读 inventory 一次、无 fill/Continue/submit 参数，并把成功 preflight 路径保留到最终报告。当前 speed runner 回归为 `29 passed`，全仓库为 `2537 passed, 1 skipped`。真实 Quick Apply inventory 尚未运行，因此上面的 live checklist 和 checkpoint pass 仍未完成；没有 live fill 或 submit。

---

### Checkpoint 15A: 真实网站单个低风险文本字段

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Modify: `tests/test_seek_speed_demo_runner.py`
- Update: `docs/SEEK_NO_SUBMIT_UAT.md`

- [x] 在执行前生成可审查的单字段预检，显示字段、脱敏值来源/hash/length、风险、目标界面和截图/Trace 证据。
- [ ] 用户审核该预检并给出与报告 SHA-256 和字段 ID 绑定的明确 live-fill 批准。
- [ ] 使用当前截图重新定位一个姓名或联系方式字段。
- [ ] 经过 policy Gate 和真实 Action Gate 后填写一次。
- [ ] post-observe 验证 hash/length；Trace 审计原始 PII 不泄露。

**Checkpoint pass:** `live_safe_fill attempted=1/passed=1`、`submit_clicks=0`。这只证明单字段，不证明完整表单。

**CP15A safety preparation (2026-08-03):** timed runner 已改为默认 fail-closed。非只读分支缺少显式 `--approve-live-safe-fill` 时，会在任何 `continue_application_flow` 调用前以 `live_safe_fill_approval_required` 停止；即使具备该开关，仍必须提供唯一匹配当前 answer plan 的 `--approved-live-field-id`。字段 ID 缺失、未知、重复或滚动刷新后不再匹配时均在输入前停止。该 ID 已贯通 speed -> debug -> traversal runner，CP15A 固定最多一个字段，并移除隐式 cover-letter 授权。聚焦 traversal/debug/speed/form-safety 回归为 `184 passed`，全仓回归为 `2542 passed, 1 skipped`，相关脚本编译通过。这只是批准和身份绑定前置条件，不等于字段值批准、live-fill 授权或成功证据；真实单字段填写仍未运行。

**CP15A preflight binding (2026-08-03):** `--prepare-live-safe-fill --prepare-live-safe-fill-field-id <id>` 现在复用只读 inventory 生成 `seek_live_safe_fill_preflight_v1`，只保留字段语义、脱敏 answer source/hash/length、当前表单状态、截图/Trace 路径、安全限制和 post-observe 预期，然后停止。批准分支还必须提供 reviewed preflight 路径及 SHA-256；checksum、contract、字段 ID 或安全声明不一致时，在任何 live-fill runner 调用前 fail closed。speed runner 为 `35 passed`，相邻 traversal/debug/speed/report-audit 为 `155 passed`，全仓为 `2546 passed, 1 skipped`。真实用户批准、单字段 live fill 和 post-observe 仍未运行。

**CP15A panel review projection (2026-08-03):** 现有 workflow audit 区域新增折叠式脱敏预检加载器。后端只接受 `artifacts/` / `logs/` 下的 `seek_live_safe_fill_preflight_v1`，校验 PII redaction 后只返回白名单字段；前端显示字段、answer source/hash/length、post-observe 验证和一字段/Continue/submit 边界，并明确 `artifact_is_authorization=false`。真实本地面板浏览器 smoke 已加载该卡片；首次失败被定位为旧 Uvicorn 进程缺少新路由，重启当前代码后通过，没有添加兜底。验证为 JS `28 passed`、panel route `129 passed`、speed runner `35 passed`、全仓 `2549 passed, 1 skipped`。该卡片只是审查入口，不会设置批准参数或执行填写。没有模型、live fill、Continue 或 submit。

---

### Checkpoint 15B: 真实网站一个表单步骤

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Modify: `tests/test_seek_speed_demo_runner.py`
- Update: `docs/SEEK_NO_SUBMIT_UAT.md`

- [ ] 逐个处理当前步骤允许字段；未知问题立即暂停。
- [ ] 将非最终按钮分类为 `continue_next_step`，经过 Gate 后点击一次。
- [ ] 重新 observe 并验证进入新步骤；旧 inventory 和坐标全部作废。
- [ ] 保存每个字段和 transition 的 Trace。

**Checkpoint pass:** 一个真实步骤完整走通，仍不点击最终提交。

---

### Checkpoint 16: 第一条完整 no-submit UAT

**Files:**
- Modify: `scripts/seek_speed_demo_runner.py`
- Update: `docs/SEEK_NO_SUBMIT_UAT.md`

- [ ] 从首页列表开始，滚动读取新岗位，避免重复卡片。
- [ ] 打开岗位详情并滚动到明确 `reached_bottom` 或安全停止状态。
- [ ] Agent 基于最新完整详情决定是否进入 Quick Apply。
- [ ] 逐步骤 inventory、回答、定位、Gate、执行和验证；未知问题允许人工确认。
- [ ] 在最终审核页识别 final submit 并 safe-stop。
- [ ] 将列表、岗位详情、Quick Apply 表单步骤和最终审核页保存为同一软件下的正式多界面学习流程；每条 transition 绑定来源界面、来源控件、语义动作、目标界面和验证规则。
- [ ] 发布后的流程必须写入 `artifacts/interface-workflow-reviews`，可由面板重新加载，也可投影为 Agent 可读取的界面与动作上下文；单次 `learning-runs` 目录不能代替正式流程资产。

**Checkpoint pass:** 完成一次列表到最终审核页的 no-submit UAT，保存并重新加载对应的正式多界面学习流程，或留下唯一明确阻断层；`final_submissions=0`。

### Checkpoint 16A: 经审核文件上传

- [ ] 文件上传控件来自当前 inventory 和当前截图，不使用历史坐标。
- [ ] 文件证据绑定绝对路径、SHA-256、大小、扩展名和人工批准；报告只保留脱敏投影。
- [ ] 点击上传控件、原生文件选择器输入和重新 observe 分步执行并记录 Trace。
- [ ] 本地真实 GUI fixture 验证文件名哈希和大小，且 `submit_clicks=0`。
- [ ] 学习资产只保存上传控件语义，不保存本地文件路径，也不构成上传授权。

**Checkpoint pass:** 受控 fixture 中真实选择一个经审核文件并验证效果；不点击 Continue 或 final submit。真实 ATS 上传仍需当前文件与字段的明确批准。

---

### Checkpoint 17: 重复性与 holdout

**Files:**
- Create: `scripts/run_generic_quick_apply_demo_benchmark.py`
- Create: `tests/test_generic_quick_apply_demo_benchmark.py`
- Create: `artifacts/benchmarks/generic_quick_apply_demo_manifest_v1.json`

- [ ] 建立 checksum、stale fixture、evidence missing 和 denominator integrity 测试。
- [ ] 运行 3 次开发路径，覆盖不同岗位和问题组合。
- [ ] 运行 1 次未用于修正策略的 holdout 表单路径。
- [ ] 分层报告 evidence、Agent、recall、grounding、Gate、effect、state verification 和 blocker。

**Checkpoint pass:** 有至少 4 次可审计尝试，其中 1 次为 holdout；不输出总成功率宣传。

---

### Checkpoint 18: Demo 收尾

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Update: `docs/SEEK_NO_SUBMIT_UAT.md`

- [ ] README 最前面提供一条 runtime/panel 启动命令和一条默认 `--no-submit` 演练命令。
- [ ] 面板演示顺序固定为：路径图 -> 当前证据 -> Agent 决策 -> Gate -> Operation effect -> Trace -> safe stop。
- [ ] 面板路径图展示同一软件的全部已学习界面和真实 transition；点击节点可切换该界面的带框证据，重新打开面板后流程仍存在。
- [ ] 用保存的多界面流程完成一次 Agent 消费验证，证明 Agent 能读取当前界面、可用动作、目标界面和验证规则；流程资产仍不构成执行授权。
- [ ] 运行 focused tests、面板 tests、full pytest 和启动健康检查。
- [ ] 输出 fixture-covered、dry-run-covered、live single-field、live single-step、full no-submit 和 holdout 的分层证据。
- [ ] 明确区分 fixture 文件上传、真实 ATS 文件上传、敏感问题自动回答和真实 final submit 的覆盖状态。

**Checkpoint pass:** 用户能从面板打开一条持久化的多界面学习流程，沿路径图切换界面证据，并演示该资产如何帮助 Agent 决策和安全完成 no-submit 流程；所有结论都有可复跑证据。

---

## 执行纪律

1. 每次只推进一个 checkpoint；未通过时不进入下一关。
2. 每关先写失败测试，再写最小实现，再做最窄运行验证。
3. fixture 先于 live；单动作先于单步骤；单步骤先于完整流程。
4. live fill 必须单独获得用户明确批准；计划批准不等于 live 动作批准。
5. 每关完成后只汇报 changed files、attempted/passed/failed/invalid/not_covered、Trace、截图、安全影响和剩余 blocker。

## 预计剩余工作量

- CP9A 到 CP12B：2-3 个集中工作日。
- CP13 面板演练：0.5-1 个集中工作日。
- CP14 到 CP16 live UAT：1-2 个集中工作日，取决于登录、ATS 页面和模型/GPU 状态。
- CP17 到 CP18 回归与收尾：1-2 个集中工作日。
- 当前合理估计：4.5-8 个集中工作日。Demo 可展示的最早门槛是 CP16；阶段性收尾门槛是 CP18。
