# Simple Native Provider Smoke Design

**Date:** 2026-09-03

**Status:** Phase A implementation-ready; Phase B intentionally deferred

**Baseline:** `1194d3ddc35b7c4f7fa39ace728bfff529923504`

## 1. Goal

先用每个模型最容易稳定生成的原生小协议，跑通现有 5 屏 regression diagnostic，尽快得到 OmniParser、Qwen、VISTA 三个真实模型的准确率与失败类型。Phase A 不抽象统一的大型 provider protocol，不扩大 Benchmark infrastructure，也不改变 Learning schema。

Phase A 的唯一范围是：

1. A1：纯 parsers/contracts；
2. A2：可注入、可离线 replay 的 runner；
3. A3：5 屏 CLI/config；
4. A4：连接实际 caller，但默认绝不启动模型；
5. A5：同步文档。

真实模型启动是显式操作：没有用户在当次任务中批准，不得加载权重、启动模型服务或运行 actual 模式。

## 2. 仓库证据与边界

### 2.1 Qwen 当前边界

- `app/learn/hybrid/qwen_binding.py::build_qwen_binding_request` 构建完整 runtime request，包含 `capture_id`、截图引用与 SHA、尺寸、完整候选几何、OCR/UIA sealed context、`context_ref`、语义版本和允许字段。
- `app/core/model_server.py::_qwen_binding_response_schema` 当前要求模型为每个 candidate 输出 `candidate_id`、`role`、`label`、`binding_status`、`confidence`。
- `app/core/model_server.py::run_qwen_binding_model` 当前把完整 canonical runtime request 直接放进模型 prompt。
- `tests/test_learn_hybrid_qwen_binding.py` 已覆盖 unknown/duplicate/omitted/reordered ID、几何篡改、UTF-8 label、截图与 context 绑定。

结论：完整 runtime request 是安全与证据边界，必须保留；问题仅在 model-facing payload 过重。Phase A 在完整 request 通过既有校验后生成短 projection，模型只处理短 ordinal，adapter 再恢复稳定 candidate ID，并继续调用既有 parser。

### 2.2 OmniParser 当前边界

- `scripts/run_uei_omniparser_shadow_worker.py::_run` 从官方结果读取 `bbox`、`type`、`content`、`interactivity`，目前同时补齐 runtime ID、像素 bbox、role/state、coordinate space、duration/resource。
- `app/learn/recognition/uei/omniparser_shadow_adapter.py::_normalize_worker_output` 与 `_normalize_item` 校验边界并生成 `NormalizedProviderItem`。
- `app/learn/recognition/uei/provider_adapters.py::NormalizedProviderItem` 与 `NormalizedScreenParseOutput` 是现有 Learning 消费形状。
- `tests/test_uei_v1_omniparser_shadow_worker.py` 已覆盖准确坐标投影、质量过滤、role/interactivity 与 malformed output。

结论：模型原生层只保留官方字段；runtime 字段由 adapter 统一附加，既有 Learning 输出不变。

### 2.3 VISTA 当前边界

- `scripts/model_servers/vista_openai_server.py::_vista_prompt` 已规定模型返回中心点 `[x,y]`。
- `scripts/model_servers/vista_openai_server.py::_point_payload` 可从文本提取坐标对；`_requested_coordinate_space` 默认 `normalized_0_1000`。
- `scripts/run_learn_recognition_actual_grounding_smoke.py::parse_grounding_model_output` 当前兼容 list/dict/bbox 多种形状。
- `app/vision/local_provider.py::LocalVisionProvider._call_openai_compatible_endpoint` 会添加通用 JSON system prompt 和 `response_format=json_object`，不适用于 VISTA 原生小协议。
- `tests/test_learn_hybrid_vista_refinement.py::test_vista_never_clips_or_uses_a_nearest_point_correction` 固化了失败不得裁剪或最近点纠正的原则。

结论：Phase A 的 VISTA caller 使用独立薄 HTTP 边界，只发送图片与原生定位 prompt，读取 bare normalized `[x,y]`；不得复用通用 JSON caller 的 system prompt 或 `response_format`。

### 2.4 5 屏与 scorer 隔离

- 只使用 `tests/fixtures/portfolio_hybrid_v1_1/corpus/regression/case-001.png` 至 `case-005.png`。
- provider 输入来自 `tests/fixtures/portfolio_hybrid_v1_1/provider-corpus.v2.json`；现有 `gold.v1.json` 只能由 scorer 读取。
- `tests/test_portfolio_hybrid_v1_1_benchmark.py` 已证明现有五屏是 regression-only、report 不具 promotion eligibility、provider projection 不得包含 scorer-private fields。
- 5 屏共 25 个 target。Phase A 只生成 diagnostic artifact，不产生 promotion 决策。

## 3. Model-native simple schemas

三个 schema 是彼此独立的模型原生协议，不共享 generic envelope，不要求字段对齐。

### 3.1 Omni native output

```json
{
  "items": [
    {
      "bbox": [0.10, 0.20, 0.30, 0.28],
      "type": "text",
      "content": "Search",
      "interactivity": true
    }
  ]
}
```

最小字段：

- `bbox`：长度 4 的 normalized `[x1,y1,x2,y2]`，每项有限且在 `[0,1]`，并满足 `x1 < x2`、`y1 < y2`；
- `type`：官方模型类别的非空短字符串；
- `content`：字符串，可为空但受现有长度限制；
- `interactivity`：boolean。

模型不得生成 `source_item_id`、pixel bbox、runtime role/state、capture ID 或 evidence 字段。

### 3.2 Qwen model-facing projection and output

Qwen 输入 projection：

```json
{
  "image_size": [1280, 720],
  "candidates": [
    {"i": 0, "box": [112, 84, 294, 126], "active": true}
  ]
}
```

Qwen 输出：

```json
{
  "bindings": [
    {
      "i": 0,
      "role": "button",
      "label": "New task",
      "status": "BOUND",
      "confidence": 0.92
    }
  ]
}
```

规则：

- projection 只能从已经通过现有 runtime request 校验的对象生成；完整 runtime request 仍是 provenance、freshness 与安全的 source of truth；
- `i` 是本次 projection 的零基 ordinal，不是 runtime identity；
- 输出必须按输入顺序恰好覆盖每个 ordinal 一次，不接受 unknown、duplicate、omitted 或 reordered ordinal；
- adapter 将 `i` 映射回完整 request 中对应的 `candidate_id`，将 `status` 映射为 `binding_status`，然后调用既有 `parse_qwen_candidate_bindings`；
- 模型不能输出或改变 bbox、action、capture identity、stable ID。

### 3.3 VISTA native input/output

VISTA 输入是已验证的 ROI crop 与短自然语言 target；坐标语义固定为 crop 内 `normalized_0_1000`。原生输出只有：

```json
[437, 612]
```

规则：

- 严格接受恰好两个有限数字，范围均为 `[0,1000]`；
- caller 不发送 generic `json_object` system prompt，也不发送 `response_format={"type":"json_object"}`；
- adapter 用现有 ROI transform 恢复 capture-space point；
- 点必须位于 ROI、绑定 candidate 与 capture bounds 内；任一验证失败即 abstain；
- 禁止 clipping、nearest-point correction 或 bbox fallback。

## 4. Runtime-attached fields

原生模型输出通过后，由薄 adapter 补全以下字段；这些字段不是模型生成内容：

### Omni adapter

- `source_item_id`：由 capture 与 item ordinal 确定性生成；
- `source_bbox`：使用 capture 尺寸从 normalized bbox 一次性转换为 pixel bbox；
- `source_coordinate_space`；
- `safe_text`、`safe_role`、`safe_states`；
- `source_confidence`；
- `provider_id`、`model_profile_id`；
- `duration_ms`、`resource_units`；
- capture identity、input/output hashes 与 trace lineage。

### Qwen adapter

- `candidate_id`：只可由 projection ordinal 映射恢复；
- `binding_status`：从 native `status` 规范化；
- 完整 `capture_id`、截图 SHA/尺寸、`context_ref`、semantic version 与 request/response hashes；
- 既有 `hybrid_qwen_bindings_v1` runtime shape。

### VISTA adapter

- `requested_coordinate_space=normalized_0_1000`；
- capture-space `point` 与 transform evidence；
- `candidate_id`、ROI、capture identity；
- inside-ROI/inside-candidate/inside-capture validation；
- raw UTF-8 response、parsed pair、latency 与 trace hashes。

## 5. Thin adapter and replaceable slot boundary

Phase A 只定义三个独立 callable slot：

- `OmniNativeCaller(image) -> OmniNativeOutput`；
- `QwenNativeCaller(image, QwenModelProjection) -> QwenNativeOutput`；
- `VistaNativeCaller(roi_image, target_text) -> VistaNativePoint`。

runner 构造时注入三个 callable，因此 replay fake、当前本地模型 caller 或未来替代模型均可更换。替换某一 slot 不得要求另两个 slot 变更。

不在 Phase A 引入：

- `BaseProvider`、统一 request/response envelope 或跨模型字段全集；
- capability registry、动态 discovery、provider inheritance hierarchy；
- Benchmark v2 adapter 或 Learning schema migration；
- 为预测未来模型而添加 optional field。

薄 adapter 的责任只有：严格 parse 原生输出、附加 runtime-owned 字段、调用既有 validator/consumer、保留 trace。模型生命周期、scoring 与 Learning 逻辑不进入 adapter。

## 6. Runner dataflow

1. CLI 读取固定 regression manifest，并验证 5 个 screenshot 的文件存在性、尺寸与 SHA。
2. runner 调用 Omni slot，parse 原生 items，adapter 生成既有 normalized candidates。
3. runner 构建完整 Qwen runtime request并先执行既有校验；再生成 model projection，调用 Qwen slot，恢复 stable IDs，再走既有 binding parser。
4. 对 uniquely bound、grounding-eligible target 构建已验证 ROI，调用 VISTA slot，恢复 capture point并执行严格 containment validation。
5. provider artifacts 写完并关闭 provider 输入后，scorer 才可独立读取既有 gold。
6. 输出 case-level raw trace、parsed trace、slot metrics、end-to-end diagnostic 和 cleanup receipt。

任何阶段失败都保留已获得的 raw evidence，并将该 target 计为 schema failure 或 abstention；不得用 heuristic fallback 冒充模型成功。

## 7. Compatibility strategy

- Qwen：不修改 `build_qwen_binding_request` 的完整 runtime schema；新增 projection/expansion seam，expanded response 继续进入现有 parser。
- Omni：Learning 继续接收 `NormalizedScreenParseOutput`；native parser 位于 worker/model 输出与现有 normalizer 之间。
- VISTA：现有 runtime coordinate/containment contract 不变；仅 actual caller 使用 bare pair 专用路径。
- 现有 Benchmark v2、Gold、holdout、Learning schema 均不修改。
- replay fixture 版本与原生 schema 分开记录，避免把 diagnostic artifacts 误当作 runtime API。

## 8. 不可简化的不变量

以下内容不属于“模型协议复杂度”，不得因 Phase A 简化：

1. capture ID、image size、content SHA、workflow revision 与 candidate freshness 必须一致；
2. stable runtime ID 只能由 runtime 生成，模型不得授权或伪造；
3. bbox/point coordinate-space conversion 必须显式、可复算、只执行一次；
4. Qwen 不得新增 candidate、改变 geometry 或产生 action authority；
5. VISTA 点必须通过 ROI/candidate/capture containment，失败不裁剪、不找最近点；
6. provider 输出仍为 `review_only`、`candidate_only`、`grounding_eligible=false`、`action_candidates=[]`；
7. `artifact_is_authorization=false`、`execute_binding=false`，禁止任何 click、submit、send、confirm、payment；
8. output bytes、item count、string length、timeout、cancellation 必须有界；
9. 每个真实调用保留原始 UTF-8 prompt、raw model text、parsed value、parse error、hash 与 parent lineage；
10. secret/credential 不进入 prompt、trace 或报告；
11. GPU exclusive ownership、process identity、timeout cleanup 与 cleanup receipt 必须验证；
12. Gold 只在 scorer boundary 可见；regression report 永不 promotion-eligible。

## 9. Five-screen smoke metrics

固定 denominator 为 5 screens / 25 targets。报告至少包含：

- 每 slot：attempted、schema-valid、schema-invalid、timeout、latency p50/p95、raw output bytes；
- Omni：items/screen、invalid/out-of-bounds items、target center coverage `n/25`、target overlap coverage `n/25`；
- Qwen：ordinal exact-coverage rate、BOUND/AMBIGUOUS/UNBOUND counts、role precision/recall、label precision/recall；
- VISTA：attempted uniquely-bound targets、valid normalized pairs、restored point inside acceptable region `n/attempted`；
- end-to-end：correct selected `n/25`、wrong selected `n/25`、abstained `n/25`；
- lifecycle：GPU owners observed、processes stopped、cleanup receipt verified。

准确率必须同时报告 numerator/denominator，不能只给百分比。输出标记为 `regression_diagnostic_only=true` 与 `promotion_eligible=false`。

## 10. Stop criteria

### 开始前

- 未获得当次用户明确批准：只允许 `preflight` 或 `replay`，不得进入 actual；
- screenshot/manifest/hash/config/prompt hash 未冻结：停止；
- 发现 Gold 字段进入 provider request：停止；
- 发现已存在的模型进程归属不明或 GPU 非独占：停止。

### 运行中立即停止

- capture SHA/尺寸/freshness 不一致；
- ordinal 无法唯一恢复 stable candidate ID；
- ROI transform 不可复算、坐标越界或代码试图 clipping/nearest correction；
- 任一 slot 连续 2 次 schema-invalid；该 slot 停止，其余只可继续收集不会依赖该 slot 的诊断；
- cancellation/timeout 后无法验证 process cleanup；
- raw UTF-8 trace 或 lineage 丢失；
- 任何 click/action/submit 路径被触达。

### 完成条件

- 恰好处理 `case-001` 至 `case-005`，不读取 holdout；
- metrics 使用固定 25-target denominator 并保留 abstention；
- 三个 slot 都有 raw/parsed/error trace，或明确记录未获批准而未运行；
- cleanup receipt verified；
- report 明确不具 promotion authority。

## 11. Phase B entry conditions only

Phase B 不在本设计中实施。只有同时满足以下条件，才可另开设计评审抽象 `Simple Provider Protocol v1`：

1. 用户批准的 actual 5 屏 diagnostic 至少完成一次，并使用冻结的 prompt/config hashes；
2. 三个 slot 的真实 raw trace 均足以确认稳定的最小输入/输出形状，失败已分类；
3. schema-valid、coordinate、lineage、Gold isolation、GPU cleanup 与 zero-action 不变量全部通过；
4. simple-native 路径相对同 5 屏 legacy diagnostic 的准确率有明确提升或不退化证据；
5. 至少存在第二个可替代实现或已确认的跨 slot 重复，能证明抽象来自事实而非预测；
6. holdout 未被读取、调参或用于协议设计。

Phase B 评审可以提取最小的 lifecycle、trace 与 slot registration 共性，但不得把 Omni items、Qwen bindings、VISTA point 强行合并为一个大 response schema。

## 12. Effort estimate

- A1 pure contracts/parsers：3 小时；
- A2 injectable offline runner：3 小时；
- A3 CLI/config：2 小时；
- A4 actual caller wiring（仅 mock 验证，不启动模型）：3 小时；
- A5 docs/checks：1 小时。

合计约 12 工时，即 1–1.5 个工程日；真实模型运行时间不计入，且需另行获得用户批准。
