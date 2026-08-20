# Learning Pattern Closed Loop（已重置）

Last updated: 2026-07-02.

## 当前状态

旧的 SEEK learning draft / tuning 闭环已经删除：

- `app.learn.pattern_draft`
- `GET /runtime/learning/seek/draft`
- `GET /runtime/learning/seek/tune`
- `GET /runtime/learning/fixtures/{fixture_id}/draft`
- `GET /runtime/learning/generalization`

删除原因：这套实现仍然太容易围绕现有 SEEK 资产、结构化 fixture 或 hidden-template 评分拟合结果。学习产物必须证明“模型从当前观察中学到结构”，不能把已有模板当成答案，也不能对评分后的产物做人工补丁。

## 下一版原则

新的 Learning Mode 应该从 Operation/Observe 层开始：

```text
current screen observation
-> compact evidence packet
-> Observe model prompt
-> raw model learning draft
-> draft/reference alignment evaluator
-> prompt / 参数反馈
```

约束：

- raw model output 必须保持不可补丁、可审计，并只能作为 Agent 可用性的候选证据。
- 草稿评分必须命名为 `draft_reference_alignment_score` 或 `template_similarity_score`，不能叫 model accuracy、click success rate、gate success rate 或 SEEK E2E success。
- 低覆盖率时只能回到 prompt / 参数 / evidence contract 调整，不能优化已评分产物。
- Trace 记录模型输入、模型原始输出、解析错误、评分和反馈。
- Gate 仍然阻止 final submit / send / confirm / payment / destructive actions。

## 保留内容

底层视觉模型任务 `learn_pattern_draft` 暂时保留为实验性的 Observe-model prompt 原语，后续正确学习模式可以复用或替换它。它不是公开 Learning Mode 工作流，也不会从面板或 runtime learning API 暴露。

## 新的最小试验入口

当前替代切片是：

```text
GET /runtime/learning/model_trial
```

它要求显式传入 `image_path`，然后调用新的 Observe 任务 `learn_template_draft`。模型必须返回 raw `learning_template_draft_v1`：

- `workflow_draft.states`
- `workflow_draft.action_templates`
- `interface_draft.regions`
- `interface_draft.visual_assets`
- `safety`

评分器只评估模型原始输出，不对产物补丁。评分项包括：

- 顶层合同字段是否完整。
- 必需 section 是否存在且有内容。
- `observation_only=true`、`promotion_allowed=false`、`final_submit_blocked=true`、`real_clicks_performed=0`。
- final submit / send / confirm / payment / delete 是否 hard block。
- 目标 action 语义是否匹配。

低于 draft/reference alignment 阈值时，反馈只能进入下一轮参数，例如：

- `prompt_detail_mode=enumerate_sections_then_json`
- 提高 `max_output_tokens`
- 缩短或延长 `timeout_seconds`

历史最小模型证据：

```text
artifacts\learning-runs\generic_model_trial_feedback_20260701-192334\trial_result.json
```

该 run 只证明了模型/参数/评分/反馈链路能运行，不证明通用网站学习能力或 SEEK E2E 稳定：

- attempt 0：Qwen3VL-8B，`timeout_seconds=1`，结构化 `model_error`，评分 21%。
- scorer feedback：调整 `learning_model_profile_id`、`learning_image_max_edge`、`timeout_seconds`、`prompt_detail_mode`、`max_output_tokens`。
- attempt 1：自动切到 Qwen3VL-4B，`timeout_seconds=90`，返回 raw `learning_template_draft_v1`。
- 历史 best score 曾显示为 100%，但这个旧口径不能作为 direct-use 或端到端能力证明。

边界：这是小 surface 的最小闭环证据，只能说明“模型输出 -> 打分 -> 参数反馈”链路初步可跑；完整网页/软件级学习需要固定 manifest、失败样本和分层 benchmark 验证。
