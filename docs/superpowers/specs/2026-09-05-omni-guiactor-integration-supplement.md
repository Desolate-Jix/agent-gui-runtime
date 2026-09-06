# Omni + GUIActor 接回审核与学习：补充设计

状态：已批准（含本轮四项修订）；独立 worktree 内部离线切片实施中，整体尚未完成。准确执行状态见 `docs/LEARNING_PIPELINE_STATUS.md`。本文不是实施完成报告，也不授权切换生产默认或执行真实 GUI 动作。

## 1. 这次补什么

以用户提供的选型结果为输入，补齐“模型实测 → 版本化协议 → 可见审核 → 理解/学习 → 保存重载 → 发布验收”的闭环，以及支撑这个闭环的最小开发流程。不重新开展全模型海选，不重写已有 Hybrid、UEI、工作流或安全门。

本设计补充 `docs/superpowers/plans/2026-08-25-portfolio-hybrid-v1-1-implementation-plan.md`，不是对旧计划完成状态的重新认定。旧计划中的固定 Qwen 和必经 VISTA 仅在新实验版本中被本设计替代；旧版本、历史证据及旧基准不改写。

## 2. 选型依据与边界

以下来自用户转述的另一任务结果，本任务尚未核验原始报告、模型权重或数据集：

| 组合 | 正确 | 错误 | 弃权 |
|---|---:|---:|---:|
| Omni + GUIActor + VISTA | 26 | 0 | 9 |
| Omni + GUIActor + UI-TARS | 26 | 0 | 9 |
| ScreenParser + GUIActor + 任一精修 | 24 | 0 | 11 |

样本由固定 25 目标与额外公共 10 目标组成。推荐组合完成率为 26/35（约 74.3%），弃权率为 9/35（约 25.7%）；26/26 的已回答样本正确率不能代替整体完成率。错误、弃权、超时、协议失败必须分别报告，不能剔除失败后缩小分母。

只有公共 10 目标已有“不精修成绩相同”的结论，不能推广为完整 35 目标或所有界面均不需要精修。公共 10 目标参与过选型，不能再冒充未见留出集。

本轮实现与接入回归的唯一模型数据范围是已经核验的现有 35 目标。不得访问名为 Unique 的 holdout，也不得新增、封存、探查或运行任何 unseen holdout；泛化验证属于后续单独定范围、单独批准的工作，本轮明确记录为未运行。

决策：OmniParser 找候选；GUIActor-3B BF16 做目标定位/候选选择；VISTA 保留为按需精修组件；UI-TARS 暂留替代实验，不同时扩大生产接入范围。UI-Venus 是后续速度/显存备选；ScreenParser、ScreenVLM、InfiGUI、Qwen 本轮不继续专项改造，也不凭协议兼容性推断模型能力。

## 3. 仓库当前事实

以下配置观察限于主目录 `codex/replay-v2@5510e78c`。本次进一步核验发现模型测试代码位于 `D:\agent-gui-runtime\.worktrees\simple-provider-protocol-v1`（`codex/simple-provider-protocol-v1@499c1beb`），其中已有 GoalBindingProvider、原生适配器、模型调用器及 GUIActor BF16 profile。实施须基于或复用这些已存在的接口，不把主目录缺失误判为项目缺失。选型报告已定位于 `E:\模型测试\reports\three-slot-selection-20260905\FINAL_SELECTION.md`；仍须核对其逐例机器证据后才作接入评分基线。

- `app/learn/hybrid/contracts.py` 已有严格的 capture、Omni、Qwen bindings、fusion、VISTA 协议；不是“完全没统一”。
- `configs/learn_hybrid_v1_1.json` 仍是 Omni → Qwen → fusion → VISTA → review，且为 opt-in。
- `app/learn/workflow_contracts.py` 的 `LearningPipelineMode` 仍只有 `incumbent`、`hybrid_v1_1`，缺省是前者。
- `app/learn/hybrid/review_projection.py::project_hybrid_review` 的新式入口要求五份完整父证据。直接省略 VISTA 会破坏现有约束。
- `configs/model_profiles/learn_mode_gui_actor_3b.json` 仍是 metadata-only、`launchable=false`、ROI verifier 职责，不能当作本轮实测部署清单。不得只修改标签就宣布接入。
- `package.json` 的 `npm test` 是失败占位命令，但已有 `tests/js/*.test.cjs`。测试数量不是缺口，稳定入口和生产消费链验收才是缺口。

## 4. 拟采用的边界

新实验模式命名为 `hybrid_v1_2`，配置 `configs/learn_hybrid_v1_2.json`。复用已有工作流与存储，不新增平行运行时。`incumbent`、`hybrid_v1_1` 行为及版本含义不变；请求不指定模式时仍走 incumbent。

```text
同一 capture 的图像、尺寸、窗口身份与哈希
  → Omni 原始候选及稳定 candidate_id
  → GUIActor 目标定位 / 严格候选关联
  → 确定性选择判定（不是完整语义理解）
  → 按需精修决策及结果记录
  → 原图框图 + 人工审核
  → 证据支持的语义理解/学习投影
  → 保存 → 新进程重载 → 编译校验
```

### 字段统一必须包含含义，而不仅是字段名

| 字段组 | 要求 |
|---|---|
| 来源与运行身份 | run_id、pipeline_mode、contract_version、config_id、provider_id、model_id、revision、dtype、原始结果引用；不得把 GUIActor 记成 qwen_vlm |
| 采集身份 | 复用 capture identity、image SHA、viewport size、窗口绑定及 lineage；跨屏/旧候选立即拒绝 |
| 几何 | 统一 `capture_pixel_xyxy`；保留原始坐标、ROI 变换与原始结果；不得裁剪非法点来伪造合法 |
| 候选关联 | candidate_id 必须来自本次 Omni inventory；落入多个重叠框时显式歧义，不用遍历顺序决定 |
| 分数 | score 类型、来源和是否校准明确；未提供为 null，不当作 0 或 1；检测分数、定位分数、语义分数不混用，不手工抬分 |
| 语义 | role、label、description 分别保留来源与审核状态；缺失明确为 missing，OCR 文本不冒充模型理解，GUIActor 定位分数不冒充 semantic_confidence |
| 人工修订 | model_proposal 不变，review_decisions 追加，reviewed_geometry/semantics 单独版本化；修改后重新验证引用与几何 |
| 精修 | 明确 not_requested、skipped、refined、failed、invalid；所有分支都有判定原因和父证据，不伪造 VISTA 调用记录 |
| 学习状态 | ready_for_review、needs_semantic_review、reviewed、persisted、compile_rejected 分开；审核工件不等于可执行动作 |

GUIActor 已核验原生协议为 `{"topk_points":[[x,y],...]}`、`normalized_0_1`；沿用已冻结适配器只取 top-1 的规则，不在 top-1 失败后挑选其余点。依据同一屏候选框做确定性关联，不假设模型原生返回 candidate_id；未经声明的其他多答案形状仍拒绝。若后续契约同时返回 ID，必须与点关联结果一致。每个已选 candidate 恰有一份精修结果记录，并绑定 candidate、bbox、ROI（如有）和 capture；不能用空列表代替未请求/失败原因。

审核中的 GUIActor 原始点、精修点、人工点分别保存来源，仅用于本次证据与展示。学习/编译资产不能把截图像素点变成跨截图可复用的 runtime point；执行仍须在新 capture 上重新定位并通过既有门禁。

**语义能力是单独验收项：** 定位正确不证明能生成原 Qwen 所提供的完整描述、角色、关系或上下文理解。可使用已验证 OCR/UIA 事实及人工补充，但来源必须真实；缺少下游必填语义时允许显示/保存待审核记录，不得编译成已理解、可发布资产。不自动加回 Qwen，也不增加未经验证的默认语义模型。

### 按需精修

先用离线策略测试比较 `never`、`conditional`、`always`，生产实验仅启用冻结的 `conditional`。三种策略必须对现有 35 目标逐案例报告前态→后态；任何原本正确案例的退化都是独立 regression，不能与其他案例的新增 gain 相抵。人工纠正后的成功必须作为独立 human-corrected outcome，不能回写或抬高 raw model score。

满足唯一候选、同一 capture、有效目标关联，且存在明确几何问题（如目标局部区域需更精确的点）时，才允许 conditional 调用精修。具体触发阈值由开发分区验证后写入版本配置，不得访问或使用 Unique/任何新 unseen holdout 调参；本轮不做泛化验证。

候选缺失、语义歧义、capture 不一致、候选冲突不属于精修能修复的问题；应弃权/人工审核。被要求精修却失败，不得静默使用原点并标成功；可展示原始建议，但状态仍是待审核。无需精修的合法分支不产生精修模型调用。

## 5. 人可以直接验收的交付

首个可见切片先交付三例 replay，不等完整 UI 或 35 目标回归才给用户看。最小协议、真实 adapter 和 no-action 安全门通过后，Task 2 必须立即从已核验现有 35 目标中选 1–3 个已授权固定案例做首轮实际模型 smoke：证据链必须是实际 load → actual raw output → adapter → 现有 WorkflowService，不能导入 benchmark 报告冒充结果，也不能等待 Task 4 的全部测试/CI 或后续完整 UI。三例交付覆盖：

1. 正确案例：原图、候选框、选中框、目标文字、点、真实分数及来源。
2. 弃权案例：重叠候选或缺失目标，标明为什么不选；没有“假成功点”。
3. 语义缺失/人工纠正案例：定位可用但描述缺失，人工补充后保存，新进程重载仍可看到原提议、修订及来源。

图例区分候选、选中、人工修改；不能只靠颜色。每例显示 actual-model 或 replay、组合版本、截图身份。图片与结果哈希不符时禁止叠框。低分不能通过改阈值或隐藏字段来改善观感。Task 2 的 1–3 案例是早期真实链路 smoke；后续完整回归仍只覆盖现有 35 目标，两者都不是泛化结论。

## 6. 全局约束与完成标准

- 只新增实验路径；生产默认保持 incumbent，旧 Hybrid v1.1 保持可读可回放。
- 模型输出和审核资产始终非授权；`artifact_is_authorization=false`、`execute_binding_enabled=false`、`final_submit_forbidden=true`、`real_action_requires_gate=true`。
- 本轮接入只做 no-action 验收，不点击、填表、提交或启动真实 Windows 操作验收。
- 不修改、覆盖或提交另一任务的模型评测脚本、报告及工作区文件；原始评测证据仅核验引用。
- UTF-8；本地原始截图、私密轨迹、权重及密钥不进入 Git 或外部咨询。
- 不引入新前端框架、微服务、通用调度器或大规模重构，不要求 100% 覆盖率。
- 三个可见例子、生产消费者贯通、保存重载无字段漂移、负控通过、精修调用可解释、测试命令可复用，才算接入完成。
- 实际模型验收与离线测试分开；本轮只运行已核验现有 35 目标，明确不访问 Unique、不新增或运行 unseen holdout，泛化验证留给后续单独范围；接入完成不等于允许切默认。
- `never`、`conditional`、`always` 逐案例报告迁移；原本正确案例的退化不能用其他 gain 抵消，人类纠正成功与 raw model score 完全分离。
- Task 4 只要求稳定的核心离线命令、相关回归和简短状态；实际检查 JavaScript 测试副作用后才能扩大 `npm test`，显式 allowlist 是合格入口。可选 CI 可并行但不阻断；无关既存失败只分类，不要求或声称全仓 clean。
- 本轮模型测试存储根上限为 30 GiB（32,212,254,720 bytes），不是显存预算；按用户本轮限制执行，不沿用另一任务后来的 50 GB 配额。显存另按实际硬件余量与模型准入检查，同一时刻只顺序加载一个模型；资源记录必须精确到本任务拥有的 PID/进程句柄/服务实例/临时目录，清理只作用于这些资源，禁止终止其他任务或用户拥有的进程。

后续真实 Windows 验收、泛化验证和默认切换均需各自独立明确批准。真实动作必须经过 `POST /action/execute_recognition_plan`，最终提交/发送/支付仍硬阻断。失败回退通过显式选择旧模式完成，不能悄悄换模型。
