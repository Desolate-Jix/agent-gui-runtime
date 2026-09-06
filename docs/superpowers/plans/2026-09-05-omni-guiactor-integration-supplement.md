# Omni + GUIActor 接入与工程闭环补充 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不切换默认、不执行真实 GUI 动作的前提下，将 Omni + GUIActor 接回已有审核与学习路径，证明字段贯通、按需精修和人可见验收，并补齐最小自动化测试流程。

**Architecture:** 复用 Hybrid、UEI 和既有 WorkflowService；新增 `hybrid_v1_2` 实验版本，保留 incumbent 与 Hybrid v1.1。候选选择、语义事实、精修结果、人工修订分别建模；以一条纵向可运行路径完成集成，而不是重建三套接口。

**Tech Stack:** 现有 Python/FastAPI/Pydantic、pytest、Node.js test runner、现有 JavaScript panel、UEI 内容寻址存储、现有模型生命周期管理。

**Spec:** `docs/superpowers/specs/2026-09-05-omni-guiactor-integration-supplement.md`

## Global Constraints

- 只新增实验路径；生产默认保持 incumbent，旧 Hybrid v1.1 保持可读可回放。
- 模型输出和审核资产始终非授权；`artifact_is_authorization=false`、`execute_binding_enabled=false`、`final_submit_forbidden=true`、`real_action_requires_gate=true`。
- 本轮接入只做 no-action 验收，不点击、填表、提交或启动真实 Windows 操作验收。
- 不修改、覆盖或提交另一任务的模型评测脚本、报告及工作区文件；原始评测证据仅核验引用。
- UTF-8；本地原始截图、私密轨迹、权重及密钥不进入 Git 或外部咨询。
- 不引入新前端框架、微服务、通用调度器或大规模重构，不要求 100% 覆盖率。
- 三个可见例子、生产消费者贯通、保存重载无字段漂移、负控通过、精修调用可解释、测试命令可复用，才算接入完成。
- 实际模型验收与离线测试分开；本轮只使用已经核验的现有 35 目标，不访问 Unique holdout，也不新增或运行任何未见留出集；泛化验证属于后续单独批准的范围。
- `never`、`conditional`、`always` 必须逐案例报告状态迁移；原本正确案例的退化不能与新增正确案例相抵，人类纠正后的成功与 raw model score 完全分开。
- 本轮模型测试存储根上限为 30 GiB（32,212,254,720 bytes），不是显存预算；按用户本轮限制执行，不沿用另一任务后来的 50 GB 配额。显存另按实际硬件余量与模型准入检查，同一时刻只顺序加载一个模型；资源记录必须精确到本任务拥有的 PID/进程句柄/服务实例/临时目录，清理只作用于这些资源，禁止终止其他任务或用户拥有的进程。

## 0. 执行边界与顺序

本文计划已获批准，并纳入本补充中的四项修订。2026-09-06 完成映射：`integration-20260906-r2` 已对已批准既有 35 目标完成 `never` / `conditional` / `always` 的 105 条 actual no-action 记录（每臂 27 correct / 0 wrong / 8 abstained），所有 requested VISTA 均 validated、owned cleanup 均已核验；最终明确离线集合为 252 Python + 28 JS 通过。可见审核、区域消费者、保存及新进程重载另在 web-01 always 例核验。此映射不代表完整页面/状态/动作语义、用户确认、真实 Windows 动作、生产切换、CI、全仓测试或泛化已完成；未访问 Unique。已实施与未完成部分以 `docs/LEARNING_PIPELINE_STATUS.md` 为准；下列原始任务清单不是完成报告。

```text
任务 1：基线、最小协议/安全契约和三例可见 replay
   → 任务 2：真实适配器接线；立即做 1–3 个已授权固定案例的首轮实际模型 no-action smoke
   → 任务 3：审核 → 理解/学习 → 保存重载
   → 任务 5：仅对已核验现有 35 目标做完整 no-action 接入回归及交付
任务 4：核心离线命令、相关回归与简短状态（可与 2 并行；可选 CI 不阻断任务 2 或本地交付）
```

每个切片实行“失败测试 → 最小实现 → 窄验证 → 检查 diff → 同步相关文档”。评审只设主链贯通、最终验收两个集成关口；普通字段调整不单独堆评审阶段。未经用户授权不自动 commit、push 或重置工作区。

本计划只取代旧计划在新实验版本上的固定 Qwen/必经 VISTA 假设，不撤销旧版安全不变量，不修改既有 Benchmark-v2 分区、基准臂和证据语义。

**实施基线校正（本次核验）：** 当前主目录为 `codex/replay-v2@5510e78c`，模型测试任务实际使用 `D:\agent-gui-runtime\.worktrees\simple-provider-protocol-v1`（`codex/simple-provider-protocol-v1@499c1beb`）。后者已含 `goal_binding_provider.py`、`goal_binding_native_adapters.py`、`goal_binding_model_callers.py` 和真实 GUIActor profile；以下 Create 接口必须先映射到这些已有实现，只补审核/学习接缝，禁止在旧主目录重复实现原生解析、候选关联或资源管理。实现工作区确定前不合并、不 cherry-pick、不修改任一分支运行代码。选型证据入口已定位到 `E:\模型测试\reports\three-slot-selection-20260905\FINAL_SELECTION.md`，结果导入不能替代后续真实工作流推理。

### Task 1：冻结字段语义，先交付三例可见回放

**Files:**
- Create: `docs/LEARNING_PIPELINE_STATUS.md`（跟踪的模式、能力、字段来源和验证状态表）。
- Create: `configs/learn_hybrid_v1_2.json`（实验组合，rollout_mode=opt_in）。
- Create: `app/learn/hybrid/selection_contracts.py`（候选选择、语义状态、精修记录的封闭校验）。
- Create: `app/learn/hybrid/selection_review.py`（新父证据集合的投影，不放宽旧投影）。
- Create: `tests/fixtures/learn_hybrid_v1_2/manifest.json`（三份合成/可公开回放样本及图像摘要）。
- Create: `tests/test_learn_hybrid_selection_contracts.py`、`tests/test_learn_hybrid_selection_review.py`。
- Modify: `app/web_panel/panel.js` 的 Hybrid 审核渲染入口，优先抽离新增渲染到 `app/web_panel/learning_selection_review.js`，不重排整文件。
- Create: `tests/js/panel_learning_selection_review.test.cjs`。
- Reference: `app/learn/hybrid/contracts.py`、`review_projection.py`、`tests/js/panel_learning_hybrid_review.test.cjs`。

**Interfaces（新增）:**
```python
def validate_target_selection(value: dict, *, inventory: dict) -> dict: ...
def validate_refinement_record(value: dict, *, selection: dict) -> dict: ...
def project_selection_review(*, capture_bundle: dict, omni_inventory: dict,
                             target_selection: dict, refinement_record: dict) -> dict: ...
```

返回封闭字典，版本分别为 `hybrid_target_selection_v1`、`hybrid_refinement_record_v1`、`hybrid_selection_review_v1`。复用旧 capture/Omni 验证器，不复用 Qwen bindings 名义承载 GUIActor 选择结果。

- [ ] 记录 `git status --short`、当前模式与用户选型结论；核验另一任务的原始报告引用、样本 manifest、模型 revision/dtype 和评分器版本。缺失证据只阻断“实测配置已复现”，不阻断合成回放开发。GUIActor metadata-only 配置不得作为真实加载证明。
- [ ] 在状态表列出每个关键字段的 producer → adapter → fusion/selection → review → learning → persisted/reloaded consumer，以及坐标、空值、来源、版本含义。对照设计文档字段表，显式区分定位能力与语义能力。
- [ ] 写失败测试：未知 candidate_id、跨 capture、非法坐标、重复 ID、NaN 分数、authority 注入、人工修订覆盖原提议均拒绝；缺失语义保留待审核，missing score 显示“未提供”，不补零。逐一篡改父证据的哈希/引用必须拒绝，同一完整父集合必须可确定性重建投影。
- [ ] 实现上述严格契约和新审核投影。精修即使未调用也有 `not_requested` 记录及父引用，旧 `project_hybrid_review` 的五父输入规则不变。
- [ ] 提供正确、弃权、语义缺失/人工修订三例；先标 `replay`。UI 同时显示原图、全部候选、选中目标、原始/精修点、分数类别、语义来源、拒绝原因和组合版本。不同状态既有颜色也有文字/图例；缩放不改变存储坐标。
- [ ] 运行以下窄验证，预期新用例及旧 Hybrid 契约通过；人工打开三例，核对框确实落在对应图片上，保存截图到忽略的 artifacts，不把截图存进 Git。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_learn_hybrid_selection_contracts.py tests/test_learn_hybrid_selection_review.py tests/test_learn_hybrid_contracts.py
node --test tests/js/panel_learning_selection_review.test.cjs tests/js/panel_learning_hybrid_review.test.cjs
```

**关键断言模板：** 输入由三例 manifest 中同名样本提供，测试 fixture 只读取 UTF-8 JSON 并做深拷贝。
```python
def test_review_keeps_missing_semantics_explicit(review_missing_semantics):
    assert review_missing_semantics["learning_state"] == "needs_semantic_review"
    assert review_missing_semantics["artifact_is_authorization"] is False
    assert review_missing_semantics["execute_binding_enabled"] is False
```

**交付门：** 用户先能看到三例，而不是只有测试通过数字；此时不得把 replay 称作实际模型结果。

### Task 2：接真实选择适配器并立即做首轮实际模型 no-action smoke，不偷换语义

**Files:**
- Create: `app/learn/hybrid/target_selection.py`（GUIActor 原生结果关联到 Omni 候选）。
- Create: `app/learn/hybrid/refinement_policy.py`（纯函数决策与调用记录）。
- Create: `app/learn/workflow_tasks/hybrid_selection.py`（既有 worker 内的实验处理链）。
- Modify: `app/learn/workflow_contracts.py`、`workflow_service.py`、`workflow_worker.py`（新增模式及 task 注册，小范围分派）。
- Modify: `app/api/panel.py`（显式实验模式与 readiness，默认不变）。
- Modify: `configs/learn_hybrid_v1_2.json`；核验后更新 `configs/model_profiles/learn_mode_gui_actor_3b.json`，不得抹掉实际部署与 metadata-only 的区别。
- Create: `tests/test_learn_hybrid_target_selection.py`、`tests/test_learn_hybrid_refinement_policy.py`、`tests/test_learning_workflow_selection_mode.py`。
- Output, ignored: `artifacts/learning-selection-smoke/<run_id>/` 下 1–3 个固定案例的实际加载、原始输出、WorkflowService 结果、资源所有权和清理记录。
- Reference: `app/learn/hybrid/omni_discovery.py`、`vista_refinement.py`、既有模型服务生命周期边界；生产代码不得导入另一任务 benchmark runner，也不得把已导入的 benchmark 报告当作 smoke。

**Interfaces（新增）:**
```python
def parse_gui_actor_selection(raw: dict, *, capture_bundle: dict,
                              omni_inventory: dict, target_text: str) -> dict: ...
def decide_refinement(*, selection: dict, policy: dict) -> dict: ...
```

`parse_gui_actor_selection` 返回 Task 1 的 `hybrid_target_selection_v1`；`decide_refinement` 返回 Task 1 的 refinement record，未调用时不含伪造 provider result。真实 provider 调度复用项目现有模型管理入口，不在解析函数里启动模型。

- [ ] 复用已核验 GUIActor 原生 `topk_points` / `normalized_0_1` 的冻结 top-1 适配规则及脱敏 fixture，先写消费者接缝测试：只有 top-1 唯一合法包含候选才建立 candidate_id，失败后不能改取 top-2/3；未经声明的其他多答案形状、零匹配、重叠匹配分别明确拒绝/歧义。同时返回 ID 时必须一致。没有真实样本时使用注明 synthetic 的测试，实际适配验收保持未完成；不重复实现已有原生解析器。
- [ ] 写模式测试：未指定模式仍 incumbent；旧 hybrid_v1_1 不变；新模式只有组件 ready 才启动，缺少 provider 返回结构化 not_ready，不静默回退 Qwen。
- [ ] 实现选择结果的几何验证、来源保留和状态机；分数只保留真实输出，不用 GUIActor score 满足旧 Qwen semantic_confidence 门限。
- [ ] 写精修调用次数测试，随后实现纯策略：唯一候选且几何需要精修才调用；已有合法点且无触发条件为 skipped；跨屏、歧义、无候选不调用；调用失败/越界分别为 failed/invalid，不裁剪点或伪造成功。每个已选 candidate 恰有一份密封 refinement record；refined 点同时满足候选框、ROI 和变换一致性。
- [ ] 复用 VISTA ROI 验证及生命周期。UI-TARS 保持替代实验、不接入默认调度；新增语义无依据时不添加补救模型。开发分区决定的具体几何阈值须连同样本哈希、policy_version 记录后再冻结。
- [ ] Task 1 的最小契约/安全门和本任务 adapter 窄测试通过后，立即从已核验现有 35 目标中取 1–3 个已经授权且固定的案例做首轮实际模型 no-action smoke：必须是实际模型 load → 原生 actual output → adapter → 现有 `WorkflowService` 请求/任务/结果链，保留 raw output 与父引用，禁止动作 API。不得用导入 benchmark 报告、fixture replay 或 metadata-only profile 冒充真实 smoke；不得等待 Task 3 全部 UI、Task 4 全部工程项/CI 或 Task 5 完整 35 目标。
- [ ] smoke 遵守 30 GiB 测试根存储上限；显存必须满足本机实际余量及模型准入，不能把 30 GiB 当作可用 GPU 容量。顺序执行、任一时刻只加载一个模型。运行前后记录本任务精确拥有的 PID/进程句柄、服务实例、模型 revision、临时目录和显存；取消/失败也只清理这些资源并验证释放，禁止按名称批量杀进程、关闭别人的模型服务或终止其他任务/用户资源。
- [ ] 运行以下离线测试并检查请求→任务→结果→UI 的 pipeline_mode/config_id/provider_id 一致。用假 provider 验证超时、取消、重试不会重复写已完成结果；离线测试本身不启动 GPU 模型，实际 GPU smoke 仅按上一条独立执行和记录。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_learn_hybrid_target_selection.py tests/test_learn_hybrid_refinement_policy.py tests/test_learning_workflow_selection_mode.py tests/test_learn_hybrid_vista_refinement.py tests/test_learning_workflow_task_boundaries.py
```

```python
def test_ambiguous_selection_never_requests_refinement(ambiguous_selection, conditional_policy):
    result = decide_refinement(selection=ambiguous_selection, policy=conditional_policy)
    assert result["status"] == "not_requested"
    assert result["reason"] == "ambiguous_selection"
```

**交付门：** 新模式离线全链可跑，旧模式回归不退化，并已完成 1–3 个固定案例的 actual-model no-action smoke，证据贯穿实际 load → actual output → 现有 WorkflowService 且资源清理可核验；不是把配置里的 qwen 字符串换成 GUIActor 或导入旧报告就算完成。Task 3/4 的完整 UI、CI 和 Task 5 的完整 35 目标均不得成为这次早期 smoke 的前置条件。

### Task 3：贯通审核、理解/学习和保存重载

**Files:**
- Modify: `app/learn/hybrid/selection_review.py`（审核记录应用与学习投影）。
- Modify: `app/learn/workflow_service.py`、`app/learn/workflow_worker.py` 中既有审核保存/重载/编译调用点，保持既有 CAS、revision 和发布权限。
- Modify: `app/web_panel/learning_selection_review.js` 及其 panel 挂接点。
- Create: `tests/test_learn_hybrid_selection_roundtrip.py`。
- Modify: `tests/js/panel_learning_selection_review.test.cjs`。
- Reference: `app/learn/hybrid/review_projection.py::apply_hybrid_review_decisions`，复用追加修订原则。

**Interfaces（新增）:**
```python
def apply_selection_review_decisions(projection: dict, *, decisions: list[dict]) -> dict: ...
def project_selection_learning(projection: dict) -> dict: ...
```

返回审核版本仍为 `hybrid_selection_review_v1`，通过 revision 表达修订；学习输出必须经过现有学习消费者的契约校验。若该消费者无法表达 missing semantics，则返回 `compile_rejected` 和缺失字段清单，不篡改现有必填字段定义。

- [ ] 用 Task 1 的三例写生产消费者契约测试，不仅验证 adapter 自己的输出。覆盖：原始 proposal 不变、中文文本无损、坐标不二次转换、provider 不改名、missing 不变成空字符串/0、人工来源不伪装成模型。
- [ ] 沿审核保存、学习理解、编译的真实调用链补最小映射；新模块集中映射，不在每层加入互相不同的兼容字段。语义未齐可以保存为待审核，但编译/发布必须明确拒绝。GUIActor/精修/人工点各自保留证据来源，编译产物不得包含可复用的授权 runtime point；新增负控验证旧截图点不能绕过重新定位与门禁。
- [ ] 修订与选择结果同时保存到已有存储。关闭测试拥有的进程/存储连接，用独立新进程重新加载，逐字段比较原提议、人工修订、父证据、分数来源和学习状态。
- [ ] 前端执行一次人工改框和一次语义补充，保存并刷新；界面区分“模型原提议”“人工修订”“尚缺字段”。并发旧 revision 保存必须报冲突，不能覆盖新修订。
- [ ] 运行下列测试，完成第一次集成评审，检查实际 diff 与消费者断言，而非只看新契约测试数量。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_learn_hybrid_selection_roundtrip.py tests/test_learn_hybrid_selection_review.py tests/test_uei_provider_neutral_review.py
node --test tests/js/panel_learning_selection_review.test.cjs tests/js/learning_workflow_review.test.cjs
```

```python
def test_missing_semantics_cannot_compile(review_missing_semantics):
    result = project_selection_learning(review_missing_semantics)
    assert result["learning_state"] == "compile_rejected"
    assert result["missing_fields"]
    assert result["execute_binding_enabled"] is False
```

**交付门：** 至少一条真实生产消费者路径完成“提议→纠正→学习→保存→新进程重载”；缺失语义的负例仍拒绝编译。发布本身不在此步骤执行。

### Task 4：补核心离线命令、相关回归与简短状态，不搞大规模工程化

**Files:**
- Modify: `package.json`、`pyproject.toml`、`README.md`、`README.en.md`。
- Create: `scripts/check_learning_integration.py`（确定性测试 allowlist，失败即非零）。
- Create: `tests/test_check_learning_integration.py`。
- Optional create: `.github/workflows/learning-contracts.yml`（可并行补充的 Windows 无模型确定性检查；不是本地验收或任务 2 smoke 的阻断项，只配置不声称远程运行已通过）。
- Modify: `docs/LEARNING_PIPELINE_STATUS.md`。

- [ ] 先逐个检查拟纳入入口的实际 JavaScript 测试及其 setup/teardown，确认不会启动模型/GPU/GUI、访问网络、写共享状态或遗留进程；在未完成该检查前不得把 `tests/js/*.test.cjs` 作为 blanket `npm test`。允许且优先采用下面这种显式、诚实的稳定集合。

```powershell
npm test
.venv/Scripts/python.exe scripts/check_learning_integration.py --suite fast
.venv/Scripts/python.exe scripts/check_learning_integration.py --suite integration
```

`npm test` 初始固定为 `node --test tests/js/panel_learning_selection_review.test.cjs tests/js/panel_learning_hybrid_review.test.cjs tests/js/learning_workflow_review.test.cjs tests/js/uei_provider_neutral_review.test.cjs`；只有逐文件副作用检查完成后才可扩大。`fast` 固定包含 selection_contracts、selection_review、target_selection、refinement_policy 四个新测试文件；`integration` 包含 fast、workflow_selection_mode、selection_roundtrip，以及与本次主链直接相关的既有 hybrid_contracts、hybrid_review、UEI provider-neutral review，并运行上述显式 npm 集合。runner 使用 `sys.executable -m pytest` 和 `subprocess.run(..., check=True)`，Windows npm 使用 npm.cmd，避免 shell 拼接；任一选定子命令非零则总命令非零，不跳过失败后报绿。

- [ ] 在 pytest 配置注册 `model`、`live`、`gpu` 标记；本次触及的测试按实际依赖标记。旧测试尚未全量分类时默认入口采用明确 allowlist，不声称 `pytest -m 'not live'` 已足够隔离全仓。
- [ ] 只运行核心确定性离线命令和与改动直接相关的回归。若发现既存、无关失败，记录精确测试名/命令/原因及与本次 diff 无关的证据，单独分类为 unrelated existing failure；不得为报绿而放宽门禁/无理由 skip/xfail，也不得据此声称或要求“全仓 clean”。
- [ ] 可选地并行配置 Windows CI：按锁文件安装依赖 → 运行上述显式 npm 集合 → fast/integration；不下载权重、不使用私密截图或云端 GPU。CI 配置、远端运行及分支保护都不是 Task 2 smoke 或本地交付的 blocker；未运行就明确写 `CI not run`。
- [ ] 状态文档和 README 只写简短、可核验状态：implemented / integrated / default / offline-tested / actual-model-tested / human-accepted，以及真实命令、通过项、相关失败和 unrelated existing failure。仅当本次行为实际影响状态图时才同步双语状态图；不扩写无关架构，不把私密材料强行纳入 Git。
- [ ] 写一页任务卡模板：可见结果、目标模式、非目标、正例/负例、测试命令、回退方式。多任务约定文件归属及模型进程所有权，必要时 worktree 隔离；最终由一个集成者检查，禁止同时改同一主链文件。

**交付门：** 新开发者可以靠 README 的显式稳定命令验证主链，而不用从历史任务找命令；本地通过、相关回归、CI 未运行/可选、actual-model smoke 和完整 35 回归必须分别标注。CI 不阻断本地交付；无关既存失败只分类，不把范围膨胀成全仓清理。

### Task 5：仅对已核验现有 35 目标做完整 actual-model no-action 接入回归与发布前交接

**Files:**
- Create: `scripts/run_learning_selection_acceptance.py`（调用生产工作流入口，不另写推理捷径）。
- Create: `tests/test_learning_selection_acceptance_runner.py`。
- Create: `configs/benchmarks/learning_selection_acceptance_v1.json`（新接入验收配置，不覆盖旧 benchmark）。
- Modify: `docs/LEARNING_PIPELINE_STATUS.md`、受影响 README/本地进度文档。
- Output, ignored: `artifacts/learning-selection-acceptance/<run_id>/` 下 manifest、原始结果引用、框图、逐目标 JSONL、汇总和清理记录。

- [ ] 用 fake workflow 写 runner 测试：每个 manifest 目标必须恰有一个终态；超时/解析错误不减少分母；输出缺失、结果重复和错误来源引用导致非零；确认 runner 没有调用动作 API。
- [ ] 仅复用已经核验的现有 35 目标 manifest 做接入回归，不重选其他模型，不访问名为 Unique 的 holdout，不创建、封存、探查或运行任何新的 unseen holdout。泛化验证明确留给后续独立定范围、独立批准的工作，本轮报告必须写 `generalization validation: not run`。
- [ ] 对 `never`、`conditional`、`always` 逐案例列出前态→后态（正确、错误、弃权、超时、协议失败）及精修是否调用，再汇总调用率、端到端 p50/p95、冷/温启动与峰值显存；三臂保持同一截图/目标及模型配置。任何原本 raw-model 正确的案例若退化，必须单列为 regression，不能用另一个案例的新 gain 抵消。准确率、精修 ROI 合法率和每案例迁移分开统计。
- [ ] 同集接入门槛：conditional 的 raw-model 结果不低于已核验同集 26 个正确、不增加错误，且所有原本正确案例不得退化；所有未完成仍计入 35。人工纠正后的成功只进入独立的 human-corrected outcome，不回写、不抬高 raw model score。若无法核验原始样本、逐例基线或评分规则，不声称达到门槛，先输出证据缺口。
- [ ] 将 Task 1 三种可见案例换成现有 35 目标中的实际模型结果并显著标 actual-model；人工核对全部错误/弃权及选定成功样本。定位成功但语义不齐的例子仍按学习未完成报告；人工补正结果与原始模型判分并排但完全分离。
- [ ] 核验模型生命周期：测试根存储硬上限 30 GiB，显存按实际硬件准入，顺序运行且任一时刻只加载一个模型；记录本任务精确拥有的 PID/进程句柄、服务实例、revision、临时目录、显存与取消结果。只清理这些明确拥有的模型/测试资源并检查残留，禁止名称匹配式批量终止、关闭另一任务模型服务或杀掉其他任务/用户进程。保存重载和 no-action 审计同时进入验收报告。
- [ ] 最终评审输出：完成的模式/版本、字段矩阵、逐目标可见结果、失败分类、实际运行命令、回退配置、未完成项。建议是否进入单独 Windows 操作验收，但不执行，也不切默认。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_learning_selection_acceptance_runner.py
.venv/Scripts/python.exe scripts/run_learning_selection_acceptance.py --config configs/benchmarks/learning_selection_acceptance_v1.json --no-action
```

第二条用于 Task 5 的完整现有 35 目标回归；2026-09-06 已通过显式 `--out artifacts/learning-selection-acceptance/integration-20260906-r2` 实际运行，结果及精确命令见最终交付报告。它没有替代 Task 2 的早期 smoke，也未访问 Unique 或任何新 unseen holdout。

## 交付检查表

- [ ] 不再把“输出格式相同”当作“语义能力相同”。
- [ ] 不再把“定位对了”当作“学习理解完成”。
- [ ] 不再把“测试通过”当作“实际模型已验收”。
- [ ] 不再把“弃权无误点”当作“任务完成”。
- [ ] 不再把“模型选型胜出”当作“生产默认已切换”。
- [ ] 不因兼容旧格式而放宽 screenshot identity、坐标、来源和安全门。

## 本次计划修订核查

以下为编制阶段历史记录，不代表当前实施状态：当时已批准并纳入四项修订，但尚未执行代码、模型、GUI、CI、commit、push 或默认切换。2026-09-06 的实际交付见第 0 节和状态文档：本轮实验接入门槛已通过，其他能力及文件清理债务仍明确列出，不扩称全项目或生产验收完成。

编制阶段曾核查主目录实验配置、模式枚举、审核投影五父约束及 npm test 占位；主目录 metadata-only 状态不代表另一 worktree 的模型实现缺失。codegraph 返回 Transport closed，结构核验采用定向读取。主目录当时 Hybrid contracts/review 窄基线 61 passed；15 个 JS 文件经副作用核验后显式运行共 280 项，269 passed / 11 failed；这些是实施前主目录记录，不等于新 worktree 测试结论。后续隔离 worktree 的代码、真实模型运行、可见面板、验证与遗留缺口记录在 `docs/LEARNING_PIPELINE_STATUS.md`。

既有 ChatGPT 外部咨询曾因会话选择/桥接不兼容阻塞，不能算已获外部审查；本文不依赖其意见，也不重复发送本地截图/轨迹。
