# Portfolio Hybrid v1.1 Learn / Review Pipeline Design

This repository document preserves the operator-approved long-term Goal as the canonical design contract for Portfolio Hybrid v1.1.

## Goal

完成 **Portfolio Hybrid v1.1 Learn / Review Pipeline**。

最终系统必须能够在 **零真实 GUI 操作** 的前提下，对同一张 canonical screenshot 顺序运行：

```text
Capture
→ OmniParser candidate discovery
→ Qwen semantic binding
→ deterministic fusion
→ VISTA bounded ROI refinement
→ human review
→ save
→ restart / reload
→ compile / publish reviewed workflow
```

并通过可重复 benchmark 证明：

> Hybrid pipeline 相比现有单模型 / 双模型路径，在关键 UI target 的识别、语义绑定和精定位上具有可量化收益，同时保持 `wrong_target = 0`。

Portfolio v1 已视为完成。

**不得重新设计、破坏或扩大现有 Runtime execution boundary。**

Runtime 仍然只能执行：

```text
human-reviewed
+
published
+
identity-valid
Workflow
```

模型不得获得直接执行授权。

---

# Core Principle

本阶段的核心架构原则：

> Models may propose perception.
> Deterministic code resolves contracts.
> Humans approve executable assets.
> Runtime executes only reviewed workflows.

三个模型不是投票关系，而是 cascade：

```text
Omni
负责候选召回

↓ immutable candidate IDs

Qwen
负责语义理解和 candidate binding

↓ deterministic fusion

VISTA
负责 bounded ROI 内的精定位

↓ review

Human
负责最终确认

↓ reviewed workflow

Runtime
负责确定性执行
```

任何模型不得跨越自己的权限边界。

## Managed Learn orchestration

Hybrid mode 作为现有 Learn service 内的受管 pipeline variant 实现，不增加新的 public Runtime Contract，也不修改执行 Runtime。正式顺序固定为：

```text
server-owned Capture sealing
→ panel_learning_hybrid_omni_discovery
→ panel_learning_hybrid_qwen_binding
→ deterministic hybrid fusion
→ existing bounded calibration service（VISTA）
→ existing Large Review
→ existing save / reload / compiler / publisher
```

所有 managed worker 都属于 Learn 的 `screen_understanding`/review preparation 边界；不得创建一套平行 Workflow/Runtime。Qwen binding 必须实际消费 sealed Omni candidate IDs 与 geometry，而不是仅对自由文本 screen map 做离线 overlap。Hybrid mode 不调用现有 VISTA 后的 Qwen review/repair 来改变 candidate identity；VISTA 后直接进入 Human Review。

现有 incumbent Learn path 在 benchmark 完成前保持可用且默认行为不变。只有 sealed holdout 同时通过预声明的收益、coverage、`wrong_target = 0` 和 cleanup gates 后，Hybrid mode 才可以成为默认 Learn path；否则保留为 explicit/experimental mode，或把无稳定收益的 VISTA 降级为 bounded optional provider。

---

# Hard Constraints

以下约束在整个 Goal 中必须保持成立。

## 1. Zero live execution

整个 Hybrid v1.1 开发和验收期间：

```text
real_clicks = 0
live_fills = 0
live_submits = 0
```

不得因为测试 Hybrid pipeline 而触发真实 GUI 操作。

不得进入真实 Apply execution。

## 1A. Test interface cleanup

测试只允许创建显式标记为 test-owned 的静态 native 界面、专用 browser process/profile、local fixture、model process 或 helper process。不得把用户已经打开的浏览器 session、tab 或应用窗口用作陌生界面验收目标。

测试开始前必须记录 PID、HWND、process command line/profile 和已存在界面 inventory；每个新建测试对象必须记录其精确 identity。清理必须通过 process/service lifecycle 完成，不允许用 GUI click、type、keypress、shortcut、navigation 或 tab/window close 操作完成清理。若无法通过非 GUI 生命周期关闭测试对象，本次验收停止并标记 blocked，不得宣称完成。

Cleanup must satisfy:

```text
test_owned_interfaces_remaining = 0
test_owned_model_processes_remaining = 0
user_preexisting_interfaces_closed = 0
```

最终验收必须证明精确的 test-owned PID/HWND 已消失，同时 pre-test inventory 中的用户既有 PID/HWND 仍然存在。零动作计数必须至少覆盖：

```text
real_clicks = 0
live_fills = 0
live_submits = 0
live_scrolls = 0
live_keypresses_or_types = 0
focus_driven_target_actions = 0
navigation_clicks = 0
gui_window_close_actions = 0
```

最终 evidence package 必须记录测试创建对象、pre/post inventory、清理方法和逐 identity 清理结果。

---

## 2. Preserve Portfolio v1

不得破坏当前已经完成的：

* Review workflow
* workflow persistence
* workflow reload
* compilation / publication
* Runtime
* Gate
* Receipt
* Safe Stop
* Quick Apply bounded demo

如 Hybrid 与现有行为冲突：

> 优先保护 Portfolio v1，并让 Hybrid SAFE_STOP。

不要为了 Hybrid 重写 Runtime。

---

## 3. Same Capture Contract

Omni、Qwen、VISTA 必须来自同一 canonical capture lineage。

必须复用现有 UEI 字段，不创建语义重复的别名：

```text
capture_id
capture_lineage_ref { id, content_sha256 }
artifact_sha256
screenshot_sha256
image_size { width, height }
capture_coordinate_space
captured_at
workflow_revision
```

其中 `capture_sha256` 仅作为设计文档中的概念名；实现必须断言它与现有 `artifact_sha256` / `screenshot_sha256` 相等。`revision` 明确定义为 `workflow_revision`，不是 capture identity；capture identity 由不可变 `capture_lineage_ref {id, content_sha256}` 表示并持久化。

任何 resize/crop 派生视图必须使用现有 `affine_coordinate_transform_v1`，同时绑定 source artifact SHA 与 target artifact SHA。若输入同时携带多个格式有效但互相冲突的 lineage ref，必须 fail closed；不得按字段优先级猜测一个“更可信”的 ref。

所有模型输出必须能证明自己的 source capture。

任何：

* SHA mismatch
* size mismatch
* stale capture
* unknown transform
* coordinate-space ambiguity

必须：

```text
SAFE_STOP
or
REVIEW_REQUIRED
```

不得猜测。

---

## 4. Canonical Coordinate Space

canonical screenshot coordinate space 是唯一正式几何坐标系。

模型允许内部 resize / crop，但必须显式记录：

```text
source_space
model_space
transform
inverse_transform
```

所有最终：

```text
bbox
point
ROI
review geometry
```

必须可以无歧义恢复到 canonical screenshot space。

---

# Workstream 1 — Hybrid Capture Lineage

建立正式 Hybrid capture contract。

要求：

1. Capture 只生成一次 canonical screenshot。
2. Omni、Qwen、VISTA 都消费该 capture 或其有证明的派生视图。
3. provider result 必须保留 provenance。
4. lineage 可以被保存、加载和审计。
5. stale model result 不得绑定到新的截图。
6. 增加 mismatch regression tests。

Stop condition：

> 无法构造一个通过正常 API 被接受的 cross-capture Hybrid result。

---

# Workstream 2 — OmniParser Production Learn Integration

把 OmniParser 从 shadow / isolated / test-only 能力正式接入 Learn pipeline。

Omni 的职责只有：

```text
discover candidate UI regions
```

输出 canonical candidate 集合，例如：

```text
candidate_id
bbox_original
provider
provider_revision
confidence
capture_identity
raw provenance
```

## Candidate Geometry Rule

Omni 生成后的原始 candidate geometry 必须 immutable。

`candidate_id` 必须由 immutable provider-result identity + provider source-item identity 确定性派生。Qwen、VISTA 与 Human Review 都不得把该 ID 复用于另一个元素。

后续模型：

* 不得静默删除 Omni candidate
* 不得修改 `bbox_original`
* 不得重新使用已有 candidate ID 表示不同元素

可以新增：

```text
derived geometry
refined point
semantic metadata
review state
```

但必须保留原始 provenance。

过滤与人工修正采用 append-only 派生模型：

* sealed provider result 与 `bbox_original` 永久不可修改；
* 自动过滤只设置 `active/inactive` 和结构化 reason，不删除原始 candidate；
* 人工“删除”记录 tombstone/rejection decision；
* 人工改框生成 linked reviewed-derived geometry，不覆盖 `bbox_original`；
* 人工新增元素获得新的 human-origin candidate ID；
* reload 后 raw geometry 与 reviewed geometry 必须可分别检查和审计。

## Recall First

Omni candidate 数量多不是失败。

优先目标：

> 不漏关键目标。

不得为了让 UI 看起来干净而静默过滤低置信 candidate。

过滤只能：

* 明确记录原因
* 或改变 processing priority

不能销毁 provenance。

---

# Workstream 3 — Qwen Candidate Semantic Binding

Qwen 使用：

```text
canonical screenshot
+
Omni candidate IDs
+
candidate geometry
+
same-capture OCR/UIA context（若该 capture envelope 中可用）
```

进行全局语义理解。

Qwen 主要输出：

```text
candidate_id
role
label
description
semantic confidence
task relevance
relation
ambiguity
```

核心规则：

> Qwen 给 candidate 赋语义，而不是自由创建几何。

Qwen 不得直接覆盖 Omni bbox。

正式 Hybrid 与 incumbent 必须消费同一份 sealed OCR/UIA context；该 context 绑定相同 window binding、capture lineage、artifact SHA 与采集 envelope，并保留 provider provenance。UIA/OCR 仅能 corroborate 或暴露 conflict，不能单独把 candidate 提升为 `BOUND`。零匹配、多匹配或与 Qwen semantic binding 冲突时必须进入 `REVIEW_REQUIRED`。

如果 Qwen 判断存在重要元素但 Omni 没有 candidate：

```text
ORPHAN_SEMANTIC
```

进入人工审核。

不得自动伪造 Omni candidate。

---

# Workstream 4 — Deterministic Fusion

实现独立、可测试、尽量简单的 deterministic fusion layer。

第一版不要：

* LLM voting
* learned fusion model
* 自适应神经网络权重
* hidden heuristic
* 自动删除冲突候选

Fusion 应明确产生状态，例如：

```text
BOUND
AMBIGUOUS
CONFLICT
ORPHAN
LOW_CONFIDENCE
UNBOUND
CAPTURE_MISMATCH
REVIEW_REQUIRED
```

Fusion-to-VISTA eligibility 是版本化、机器可检查的 decision table：

| Fusion state | VISTA eligibility | Result |
| --- | --- | --- |
| `BOUND` + exact current lineage | eligible | 可生成 bounded refinement proposal |
| `AMBIGUOUS` | ineligible | `REVIEW_REQUIRED` |
| `CONFLICT` | ineligible | `REVIEW_REQUIRED` |
| `ORPHAN` / `ORPHAN_SEMANTIC` | ineligible | `REVIEW_REQUIRED` |
| `LOW_CONFIDENCE` | ineligible | `REVIEW_REQUIRED` |
| `UNBOUND` | ineligible | `REVIEW_REQUIRED` |
| `CAPTURE_MISMATCH` | ineligible | fail closed + `REVIEW_REQUIRED` |

所有 confidence threshold、tie rule、overlap rule 和 eligibility rule 必须位于 versioned configuration/contract 中，不得隐藏在实现代码中。

例如：

```text
Omni candidate exists
+
Qwen unique semantic binding
+
valid capture lineage
=
BOUND
```

而：

```text
multiple plausible candidates
=
AMBIGUOUS
→ REVIEW_REQUIRED
```

准确率优先于 automation coverage。

---

# Workstream 5 — Baseline Benchmark Harness

在引入 VISTA 前先建立可重复 benchmark。

建立固定 benchmark corpus，优先使用 repository 内安全、可公开或合成的截图。

在任何 prediction 生成前，必须先 seal corpus manifest、case IDs、截图 SHA、Gold SHA、provider/model revisions 与 scorer version。现有 five-screen corpus 只作为 regression corpus，不得继续承担最终收益证明；最终验收必须包含此前未用于开发或阈值调整的 untouched holdout。

目标规模可以逐步增长到：

```text
20–30 screenshots
100–200 important UI targets
```

每个 ground truth 尽可能包含：

```text
target identity
semantic role
label
expected bbox / acceptable region
critical / non-critical
```

Gold 只允许 scorer 消费，不得进入模型 prompt、candidate list、fusion input 或 selection logic。模型只看到 provider 真实生成的 candidate IDs；Gold 不得提供 expected candidate ID。

UIA/OCR context 必须在 benchmark manifest 中冻结为所有 causal arms 共享的相同 sealed context；不得只给 Hybrid 额外 UIA/context/inference budget。最低 release causal pair 为：

```text
incumbent: Qwen (+ same UIA) → VISTA
hybrid automatic: Omni → Qwen (+ same UIA) → bounded VISTA
```

同时保留 scorer-only role diagnostics：

```text
Qwen-only
Omni-only candidate discovery
Omni → Qwen（no VISTA）
incumbent Qwen (+ same UIA) → VISTA
Omni → Qwen (+ same UIA) → bounded VISTA
post-review reviewed asset（单独报告，不混入自动模型准确率）
```

`pre-review Hybrid artifact` 只是 `Omni → Qwen → bounded VISTA` 预测的持久化表示，不作为另一个统计 arm 重复计数。

记录：

* key target recall
* semantic binding precision
* semantic binding recall
* strict bbox IoU
* ambiguous count
* orphan count
* review-required rate
* human correction count
* wrong-target count

其中：

```text
wrong_target
```

是最高优先级安全指标。

目标：

```text
wrong_target = 0
```

`wrong_target` 定义为：任何由自动链选择或精修、且 scorer 判定 identity 错误的 candidate。人工纠正后的 post-review asset 不得抹去自动阶段的 wrong-target 记录。

必须分别报告 `abstention`、`REVIEW_REQUIRED`、automatic coverage 和 successful-correct coverage。验收前将最低 coverage/benefit thresholds 写入 versioned gate configuration，并在 holdout prediction 前把该配置 SHA 写入 sealed manifest；“零自动选择”不能通过 `wrong_target = 0`。任一错误自动选择都令该 run 的 safety-credited VISTA avoidance 为 0。

如果无法自动判断：

> REVIEW_REQUIRED 优于错误绑定。

---

# Workstream 6 — VISTA Bounded ROI Refinement

只有当：

```text
Omni candidate exists
+
Qwen semantic binding is valid
+
fusion allows refinement
```

时，VISTA 才能运行。

VISTA 不做全屏 target discovery。

VISTA 只消费 bounded ROI。

输入至少包含：

```text
capture identity
candidate ID
candidate bbox
bounded ROI
semantic target
```

输出：

```text
local refined point
confidence / evidence
```

然后由 deterministic code 转换：

```text
ROI-local
→ canonical screenshot point
```

必须检查：

```text
point inside permitted ROI
point inside bound candidate bbox
capture identity unchanged
transform valid
```

VISTA request 必须绑定 immutable `candidate_id`、`candidate_bbox_ref` 与 `roi_ref`。canonical point 必须同时位于 bounded ROI 与 bound candidate bbox 内；不得通过 clipping、clamping 或 nearest-point correction 把越界结果修回框内。

失败时：

```text
VISTA_FAILED
VISTA_OUT_OF_BOUNDS
TRANSFORM_INVALID
→ REVIEW_REQUIRED
```

VISTA 不得修改 semantic identity。

VISTA 也不得改变或重分配 `candidate_id`。只有 `BOUND` 且 exact current lineage 的 candidate 可以调用 VISTA；成功输出仍只是需要 Human Review 的 proposal，不是自动接受事实。`VISTA_FAILED`、`VISTA_OUT_OF_BOUNDS` 或 `TRANSFORM_INVALID` 不得升级或保留自动接受状态，必须进入 `REVIEW_REQUIRED`。

---

# Workstream 7 — GPU Lifecycle

RTX VRAM 按顺序释放和加载：

```text
Omni
↓ unload / release
Qwen
↓ unload / release
VISTA
↓ unload / release
```

禁止三个大型模型长期同时驻留导致不稳定。

实现并测试：

* sequential scheduling
* timeout
* cancellation
* process termination
* orphan process cleanup
* CUDA / model resource release
* failure recovery
* repeated-run stability

模型失败不得损坏 Workflow asset。

---

# Workstream 8 — Large Review Integration

Fusion 结果与 VISTA refinement 必须进入现有 Large Review。

Reviewer 至少能看到：

```text
canonical screenshot

Omni original bbox
candidate ID

Qwen semantics
confidence / ambiguity

VISTA refined point

provider provenance
capture lineage

fusion status
review warnings
```

人工可以：

* 接受
* 改语义
* 改框
* 改 point
* 新增缺失元素
* 标记不可用

但所有人工修改必须与 model proposal 分开保存 provenance。

Hybrid Review 必须复用现有 current-revision approval facts，不得新增绕过现有审核约束的 Hybrid shortcut。geometry、semantic、provenance 或 source revision 的任何修改都会使先前 approval 失效并要求重新确认。Compiler/Publish 继续执行现有 node/control/action/edge granular approval requirements。

最终：

```text
model proposal ≠ reviewed truth
```

Reviewed result 才能成为 Workflow asset。

---

# Workstream 9 — Persistence / Restart Proof

证明 Hybrid asset 可以通过确定性双编译：

```text
Learn
→ Review
→ Save
→ compile_without_publish A
→ terminate process
→ restart
→ Reload
→ compile_without_publish B
→ assert source_sha_A == source_sha_B
→ assert compiled_asset_sha_A == compiled_asset_sha_B
→ Publish B once
→ verify registry revision / CAS identity
```

Learning draft/review evidence 在重启后保持：

* candidate identity
* model provenance
* capture identity
* reviewed geometry
* semantics
* VISTA proposal point、ROI transform、candidate ID 与 provenance（全部 non-authorizing）
* review decision

Compiled/published workflow 必须继续剥离 runtime point fields；只允许保留 normalized geometry/reference evidence，不得包含可复用的 historical/runtime click point。发布后 Runtime 仍必须通过 fresh current observation、current re-grounding 与 Gate 获得一次性授权。

“Restart”定义为：终止当前 server process，启动 fresh server process，并从 exact saved bytes/CAS identity 重新加载；panel refresh、同一进程内重建或内存对象复用均不算 restart proof。Compile A/B 都必须 non-authorizing 且不得触发 Runtime action；Publish 只发生一次。验收必须记录并匹配 exact source SHA A/B、compiled asset SHA A/B、最终 registry revision、CAS identity 和 non-authorizing flags，同时证明：

1. review evidence 保留 VISTA proposal；
2. published asset 不含 reusable runtime point；
3. published asset 仍要求 fresh current grounding。

不得依赖仅存在于 RAM 的状态。

---

# Workstream 10 — Final Hybrid Benchmark

VISTA 接入后重新运行同一 benchmark。

比较时复用 Workstream 5 已 sealed 的相同 role diagnostics、release causal pair、budget、UIA/context policy、gate-config SHA 与 untouched holdout：

```text
incumbent Qwen (+ same UIA) → VISTA
Omni → Qwen (+ same UIA) → bounded VISTA
post-review reviewed asset（单独的人机系统结果）
```

回答一个关键问题：

> VISTA 是否产生了真实、可测量的增益？

如果 VISTA 没有稳定提高 point accuracy：

不要强制所有 candidate 使用 VISTA。

允许将它降级为：

```text
dense UI
small target
ambiguous point
high precision target
```

才调用的 optional refinement provider。

不要为了维持“三模型”概念而牺牲系统质量。

---

# Workstream 11 — Unknown UI Acceptance

最终进行两种此前未针对性开发的陌生界面测试：

1. 一个陌生 native desktop UI
2. 一个陌生 web UI

两者都必须由测试 harness 创建并显式登记为 test-owned。Web proof 必须使用 dedicated test-owned browser process/profile，不得复用用户现有 browser session。

只运行：

```text
capture
learn
recognition
fusion
refinement
review
save
reload
```

禁止操作真实界面。

必须证明：

```text
real_clicks = 0
live_fills = 0
live_submits = 0
live_scrolls = 0
live_keypresses_or_types = 0
focus_driven_target_actions = 0
navigation_clicks = 0
gui_window_close_actions = 0
```

并记录：

* candidate recall
* semantic binding
* VISTA point result
* conflicts
* review corrections
* final reviewed correctness
* pre-test 与 post-cleanup PID/HWND inventory
* test-owned interface/process identity 与非 GUI lifecycle cleanup proof
* `test_owned_interfaces_remaining = 0`
* `test_owned_model_processes_remaining = 0`
* `user_preexisting_interfaces_closed = 0`

---

# Required Engineering Behaviour

整个 Goal 执行期间：

## Before modifying

先审计现有实现。

优先复用现有：

* contracts
* provider abstractions
* adapters
* UEI
* workflow assets
* Review
* persistence
* compiler
* test infrastructure

不要建立平行重复架构。

---

## During implementation

保持小提交。

每个 Workstream：

```text
inspect
→ design
→ tests
→ implementation
→ focused regression
→ independent review
→ commit
```

发现 architecture conflict 时停在该 Workstream 内解决。

不要通过扩大 scope 绕开问题。

---

## Testing

持续运行：

```text
focused tests
hybrid contract tests
capture lineage tests
provider adapter tests
fusion tests
persistence tests
existing Portfolio v1 regression
```

每个关键 milestone 后必须证明旧功能没有退化。

---

# Explicit Non-Goals

本 Goal 不包括：

* Runtime autonomous planning redesign
* autonomous live clicking
* automatic final submission
* SEEK production execution
* 三模型 majority voting
* 新的第四视觉模型
* OCR 模型竞赛
* 通用 desktop agent
* multi-machine distributed runtime
* cloud deployment
* installer
* external developer SDK polish
* OSS onboarding polish
* UI redesign unrelated to Hybrid Review
* performance optimization without measured bottleneck
* chasing 100% automatic coverage

不要在完成主目标前扩展这些方向。

---

# Decision Policy

发生冲突时按以下优先级决定：

```text
1. wrong-target = 0
2. preserve reviewed-execution boundary
3. preserve capture provenance
4. correctness
5. reproducibility
6. review usability
7. coverage
8. speed
```

如果“更自动”和“更安全准确”冲突：

选择更安全准确。

如果模型不确定：

选择 `REVIEW_REQUIRED`。

---

# Final Stop Condition

只有同时满足以下条件时，本 Goal 才允许标记完成：

### Architecture

* Omni 正式进入 Learn pipeline
* Qwen 正式绑定 Omni candidate IDs
* deterministic fusion 已投入主链
* VISTA bounded ROI 已接入或通过 benchmark 证明无需全量使用
* 三者共享可证明的 capture lineage
* 只有 `BOUND` + exact current lineage 可进入 VISTA；所有其他状态 fail closed 到 `REVIEW_REQUIRED`
* VISTA canonical point 同时位于 bound candidate bbox 与 bounded ROI 内，且没有 clipping/clamping 修正

### Review

* Hybrid result 可在 Large Review 完整审核
* 所有模型 proposal 有 provenance
* 人工修改与模型 proposal 分离
* raw provider geometry、reviewed-derived geometry、tombstone 与 human-origin target 在 reload 后可独立审计
* current-revision approval 与现有 node/control/action/edge granular approval requirements 全部成立

### Persistence

完整证明：

```text
capture
→ Omni
→ Qwen
→ fusion
→ VISTA
→ Review
→ Save
→ Compile A without publish
→ Restart
→ Reload
→ Compile B without publish
→ assert identical source SHA and compiled asset SHA
→ Publish B once
```

并同时证明 review evidence 保留 non-authorizing VISTA proposal，而 compiled/published asset 不包含 reusable runtime point、仍要求 fresh current grounding；restart 必须是 fresh server process 从 exact saved bytes/CAS identity 加载。

### Accuracy

存在固定 benchmark 和机器可读结果。

在 sealed untouched holdout 上、以相同 UIA/context 与 inference budget 定量比较：

```text
Qwen-only
Omni-only candidate discovery
Omni → Qwen（no VISTA）
incumbent Qwen (+ same UIA) → VISTA
Omni → Qwen (+ same UIA) → bounded VISTA
```

post-review reviewed asset 必须单独报告，不能回写或掩盖自动阶段指标。验收同时要求预声明的最低 automatic coverage/benefit gate 通过，并证明：

```text
wrong_target = 0
```

### Real-world proof

陌生 native UI 与陌生 web UI 各完成至少一次 no-action acceptance。

并证明：

```text
real_clicks = 0
live_fills = 0
live_submits = 0
live_scrolls = 0
live_keypresses_or_types = 0
focus_driven_target_actions = 0
navigation_clicks = 0
gui_window_close_actions = 0
test_owned_interfaces_remaining = 0
test_owned_model_processes_remaining = 0
user_preexisting_interfaces_closed = 0
```

### Regression

Portfolio v1 全部关键 regression 继续通过。

---

# Completion Report

完成 Goal 时，只给出基于证据的最终报告：

## Changed

实际完成了什么。

## Architecture

最终 Hybrid 数据流和模型职责。

## Accuracy

各 baseline / Hybrid benchmark 数据。

## Human Review Cost

人工新增框、改框、改语义、改 point 次数。

## Safety

wrong-target、live action、Safe Stop 数据。

## Tested

完整测试和 regression 结果。

## Remaining Limitations

尚未解决的真实限制。

## Recommendation

Hybrid v1.1 是否已经值得冻结为 Portfolio release。

如果所有 Stop Conditions 已满足：

> **Freeze Portfolio Hybrid v1.1.**

停止继续扩展。

不要自行进入 v1.2、production agent、真实 SEEK execution 或其他新目标。
