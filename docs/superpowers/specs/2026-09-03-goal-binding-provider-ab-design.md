# Goal Binding Provider A/B Design

**Date:** 2026-09-03

**Status:** Approved for staged implementation and regression-only execution

**Baseline:** `7e2d1fbcc44c92ce3fd94f0d46fa83152284dabd`

## 1. Goal

在不改变 OmniParser、VISTA、Gold、corpus、estimand、Gate 或既有 scorer 的前提下，把 Goal Binding 从“要求模型生成项目自定义 candidate-index JSON”改为：

```text
provider-native point / bbox / top-k output
              ↓
provider-specific thin adapter
              ↓
canonical screenshot-space point
              ↓
deterministic active-candidate hit test
              ↓
GoalBindingProvider result
              ↓
existing VISTA ROI refinement and end-to-end scorer
```

本轮只替换最弱的 GoalBindingProvider 槽位。OmniParser discovery 先运行一次并冻结为 byte-identical candidate snapshot；所有 binder arm 消费同一 snapshot；VISTA-4B 保持不变。最终用同一 5 个 regression screen / 25 targets 同时报告 binder-level 与 end-to-end 结果，判断替换当前 Qwen 是否值得。

## 2. Frozen experimental question

唯一实验问题是：

> 在完全相同的 Omni candidate inventory、目标、截图、VISTA 与评分边界下，哪个 GUI grounding 模型最安全且最有效地把固定目标绑定到现有 candidate？

以下变量冻结：

- regression screenshots：`case-001.png` 至 `case-005.png`；
- target denominator：25；
- goal role / label / task context；
- OmniParser weights、runtime、prompt/config 与每屏 candidate bytes；
- VISTA-4B weights、runtime、ROI contract 与验证；
- existing Gold、corpus、estimand、Gate、scorer；
- 一次调用只处理一个 goal；
- provider 顺序、超时、GPU 独占与 cleanup requirements；
- 不读取或运行 unique holdout。

不能根据某个模型的 regression 成绩修改 prompt、图像预处理、候选映射、阈值或评分规则。只有官方模型要求的固定 preprocessing/native prompt 可以成为 provider profile 的一部分，并必须在首次评分前 seal。

## 3. Boundary: common runtime contract, native model syntax

“通用协议”位于 Adapter 之后，不位于模型生成层。不同模型不需要学习同一种 JSON：

- UI-Venus 返回其原生 point/action；
- GUI-Actor 返回 custom pointer head 的 `topk_points`；
- Phi-Ground-Any 返回其官方 point 或 bbox；
- GGUF grounding 模型返回其官方短坐标/tool-call 文本。

每个薄 Adapter 只做四件事：

1. 严格解析该 provider 已 seal 的原生输出；
2. 将坐标一次性转换到 canonical screenshot pixels；
3. 保留 raw UTF-8 output、parsed native value、model revision、artifact hash、preprocessing revision 与 lineage；
4. 调用同一个确定性 candidate mapper。

Learning、Review、Runtime 与 VISTA 只接收 canonical result，不知道前面是哪个模型。

## 4. Canonical GoalBindingProvider result

Canonical result 是 runtime-owned evidence，不是模型直接生成：

```json
{
  "contract_version": "goal_binding_provider_result_v1",
  "goal_index": 0,
  "candidate_index": 3,
  "candidate_id": "candidate/case-001/03",
  "status": "BOUND",
  "binding_basis": "native_point",
  "confidence": null,
  "canonical_capture_pixel_point": [323, 167],
  "provider_id": "ui_venus_1_5_2b_f16",
  "native_output_ref": {"id": "native-output/...", "sha256": "..."},
  "omni_snapshot_ref": {"id": "omni-snapshot/...", "sha256": "..."},
  "capture_ref": {"id": "capture/...", "sha256": "..."},
  "artifact_is_authorization": false
}
```

Closed result rules：

- `BOUND/native_point`：`candidate_index`、`candidate_id`、canonical point 必须存在，且 point 严格落在恰好一个 active candidate 内；
- `BOUND/direct_candidate_index`：只允许 incumbent control；`candidate_index`、`candidate_id` 必须存在，canonical point 为 `null`，index 必须通过现有 closed Qwen parser 并指向 snapshot 中的 active candidate；
- `UNBOUND`：`candidate_index=null`、`candidate_id=null`；原生输出可以合法但没有唯一 candidate hit；
- `PROVIDER_FAILURE`：`candidate_index=null`、`candidate_id=null`；原生输出 malformed、越界、非有限、缺失或 provider 调用失败；
- `confidence` 只保留 provider 原生、可验证的 confidence；provider 不提供时为 `null`，不得伪造 `1.0`；
- goal 的 role / label 从 frozen provider corpus 确定性继承，模型不得生成或改变；
- 模型不得生成 candidate、bbox、stable ID、action、click authority 或 review approval。

## 5. Native output normalization

### 5.1 UI-Venus

Adapter 接受 sealed official inference path 的单一 top-1 point/action 结果。若官方结果同时含动作文本和点，只读取 profile 指定的 point field；动作文本不进入 canonical result。坐标空间由 profile 明确声明并按 screenshot width/height 一次性投影。多点、缺点、附加无法解释的坐标或越界均为 `PROVIDER_FAILURE`。

### 5.2 GUI-Actor

Adapter 只读取：

```python
prediction["topk_points"][0]
```

禁止查看 Gold 后从 top-3/top-k 中挑更好的点，禁止使用第二候选作为 fallback。空列表、非法值或 top-1 越界为 `PROVIDER_FAILURE`；其余 top-k 值只保存在 raw evidence，不参与选择。

### 5.3 Phi-Ground-Any

Adapter 使用官方固定 preprocessing 与原生 point/bbox output。point 直接归一化；bbox 必须合法、非退化、位于官方 coordinate space，再以 bbox 几何中心生成一个 canonical point。禁止裁剪、nearest-candidate correction 或基于 Gold 选择 point/bbox 分支。

### 5.4 GGUF fallback

UI-Venus-2-9B、GroundNext-7B-V0、UI-Venus-1.5-8B 只有在 Stage 1 无模型通过 hard gate 时才允许执行。GGUF 与 mmproj 必须绑定 immutable revision 和 SHA；llama.cpp runtime 也必须记录 build identity。当前 b8892 不默认视为兼容 UI-Venus-2 Qwen3.5 GGUF，必须在 preflight 中实际验证 model load 与一条无 Gold 的 schema smoke。

## 6. Deterministic point-to-candidate mapping

输入只有：`goal_index`、validated canonical point、frozen active candidates、capture identity。

候选命中规则使用严格内部：

```text
x1 < point_x < x2 and y1 < point_y < y2
```

结果：

- 恰好一个 active candidate 命中 → `BOUND`；
- 0 个命中 → `UNBOUND(reason=no_active_candidate_hit)`；
- 超过 1 个命中 → `UNBOUND(reason=ambiguous_active_candidate_hit)`；
- point 在边界上 → 不算命中；
- inactive candidate 永不参与命中；
- 不允许 bbox 扩张、clipping、nearest candidate、OCR heuristic 或 top-k fallback。

这条映射是所有 provider 共用的纯函数，也是通用协议最稳定的部分。

## 7. Frozen Omni snapshot

OmniParser 在 experiment 开始时只运行一次，生成五屏 snapshot：

```text
omni-snapshot-v1/
  manifest.json
  case-001.candidates.json
  ...
  case-005.candidates.json
```

Manifest 必须 seal：

- 五个 screenshot path、size、SHA；
- Omni provider/profile/model revision；
- native output SHA；
- canonical candidate file SHA；
- candidate ordering、active flag、bbox、candidate ID；
- capture lineage；
- aggregate snapshot SHA；
- `regression_only=true`、`contains_holdout=false`、`artifact_is_authorization=false`。

Arm runner 只能读取并验证 snapshot；不得重跑 Omni 或改变 candidate order。任一 byte/hash/identity mismatch 会在启动 binder 前 fail closed。

## 8. Staged model matrix

### Incumbent control

`OmniParser snapshot → Qwen3-VL 8B Q4_K_M → VISTA-4B`

之前的 `1 correct / 5 wrong / 19 abstain` 只作为历史参考。为保证 byte-identical comparison，正式 matrix 必须让 incumbent 重新消费本轮 frozen snapshot。Incumbent 是唯一保留现有 per-goal `candidate_index` 原生输出的 control arm：它继续通过 `expand_qwen_goal_binding_response` 严格验证，再由 control bridge 投影为同一个 canonical result；不得伪造 point，也不得把 incumbent 的 candidate-index 协议强加给 challenger。Challenger 统一走 native point → deterministic hit test。

### Stage 1: full checkpoints first

1. `inclusionAI/UI-Venus-1.5-2B`，F16；
2. `microsoft/GUI-Actor-3B-Qwen2.5-VL`，BF16；
3. `microsoft/Phi-Ground-Any`，BF16。

每个 challenger 单独下载、单独启动、完整跑 25 targets、cleanup 后再进入下一个。完整模型能在 12GB GPU 上合法完成就不测其量化版。

### Stage 2: only when Stage 1 has no hard-gate passer

1. `inclusionAI/UI-Venus-2-9B` Q6_K + mmproj；
2. `GroundNext-7B-V0` Q6_K + Q8 mmproj；
3. 若 UI-Venus-2 runtime incompatible，才允许 `UI-Venus-1.5-8B` Q6_K + Q8 mmproj。

Stage 2 不是为提高排行榜而自动执行；Stage 1 有任一合格模型即停止扩展模型集合。

## 9. Storage and deletion contract

唯一实验存储根为：

```text
E:\模型测试
```

整个目录的逻辑文件大小硬上限为 `32,212,254,720` bytes（30 GiB），包括 `models/`、`cache/`、`staging/`、`runtime/`、`runs/` 与 `reports/`。规则：

1. 下载前通过 Hugging Face metadata 解析 immutable revision、文件清单和 LFS bytes；
2. 计算 `current_root_bytes + planned_download_bytes + 5% staging_margin`，超限则下载前拒绝；
3. 每个 artifact 下载到 `staging/<provider_id>/<revision>/`，完成后逐文件 hash，再原子移动到 `models/`；
4. 不使用或不合格模型在 cleanup verified 后删除 weights；保留小型 manifest、hash、license、report 与 raw score evidence；
5. 多个模型通过时只保留最终 winner weights；
6. 删除前用 `Path.resolve()` 和 `os.path.commonpath` 验证目标严格位于 `E:\模型测试`，拒绝根目录本身、symlink/reparse point、未知目录和未登记 artifact；
7. 不删除、移动或覆盖 D 盘 incumbent models/runtime；
8. 下载失败的 partial staging 也必须按同一安全删除流程回收。

## 10. Runner and lifecycle

执行顺序：

1. regression-only preflight；
2. storage inventory 与 free-space check；
3. capture/freeze/verify Omni snapshot；
4. incumbent arm；
5. Stage 1 A → cleanup → B → cleanup → C → cleanup；
6. 评分所有完成 arm；
7. 若无 hard-gate passer，才进入 Stage 2；
8. 选 winner、删除 rejected weights、重新验证 storage inventory；
9. 生成 matrix report、cleanup receipt；
10. STOP，不运行 holdout。

同一时间只能有一个大模型驻留。每个 provider phase 必须记录 exact PID + create-time、artifact identity、GPU observation、start/stop 时间、peak VRAM、request count、timeout、raw error 与 verified absence。cleanup 不能证明时，后续 arm fail closed。

## 11. Scoring

### Binder-level (new regression diagnostic)

固定 denominator 25：

- native parse success `n/25`；
- `BOUND / UNBOUND / PROVIDER_FAILURE`；
- correct bind `n/25`；
- wrong bind `n/25`；
- safe abstain `n/25`；
- latency p50/p95；
- peak VRAM；
- protocol stability；
- Omni candidate recall（只有现有 metric 可直接、无改 scorer 得到时才报告）。

Binder correctness 使用既有 frozen Gold 语义：selected candidate 满足 `acceptable_candidate_ids`，或 native point（challenger）/selected candidate center（incumbent control）位于任一 `acceptable_regions`。Gold 只在新 binder scorer boundary 读取；provider runner 不得读取 Gold。

### End-to-end (existing scorer)

- VISTA dispatch count；
- VISTA validated / out-of-bounds；
- end-to-end correct / wrong / abstain；
- VISTA gain relative to bound candidate center（现有 metric 可合法得到时）。

现有 scorer 文件与公式不修改。新 matrix report 只引用 finalized provider/binder/end-to-end report hashes。

### Promotion hard gate

每个 arm 必须同时满足：

- wrong bind / wrong target = `0/25`；
- native parse = `25/25`；
- correct bind ≥ `10/25`；
- process/listener/lease/GPU-owner residue = 0。

不通过 hard gate 的 arm 不得因加权总分高而晋级。

### Presentation score among passers only

- correct bind / coverage：40；
- end-to-end correct：25；
- protocol stability：10；
- latency：10；
- peak VRAM：5；
- VISTA gain：5；
- lifecycle cleanup：5。

## 12. Stop conditions

立即 fail closed：

- snapshot hash、capture identity、candidate order 或 geometry 变化；
- provider raw output 无法按 sealed native contract 解析；
- coordinate transform 不可复算或出现 clipping/nearest correction；
- Gold/holdout 字段进入 provider input；
- runner 打开 holdout 路径；
- GUI-Actor 使用 `topk_points[1:]` 影响选择；
- model/runtime/artifact revision 未固定；
- storage projected bytes 超过 30 GiB；
- model cleanup residue 不为 0；
- 任何 action/click/submit/send/confirm/payment path 被触达。

实际模型质量差不是 infrastructure defect：记录成绩并继续既定 arm，禁止中途调 prompt、映射或 scorer。模型无法加载、runtime 不兼容、OOM 或依赖冲突应记录为该 artifact/profile 的真实结果；只有会使所有 arm 比较无效的公共 infrastructure defect 才允许最小修复。

## 13. Deliverables

- frozen Omni snapshot 与验证 receipt；
- incumbent + Stage 1（必要时 Stage 2）每个 arm 的 provider artifact、binder report、existing end-to-end report、lifecycle receipt；
- model artifact manifests（repo/revision/path/bytes/SHA/version/license）；
- `E:\模型测试` before/after inventory；
- rejected model deletion receipts；
- final score matrix 与 winner/none decision；
- 明确声明 `regression_diagnostic_only=true`、`promotion_eligible=false`、`holdout_accessed=false`、`artifact_is_authorization=false`。

## 14. Out of scope

- 更换 DiscoveryProvider 或 PointRefinementProvider；
- 新增 ScreenParser、uitag、GUI-G2 或其他模型；
- 修改 Learning/Review/Runtime public contracts；
- 修改 Benchmark v2 supervision；
- 修改 Gold、corpus、estimand、Gate、existing scorer；
- unique holdout；
- 根据 regression 结果调 prompt、Fusion、threshold 或 mapping；
- 打包第三方 weights 进入 Git。
