# Learning Recognition Rebuild Design

> **Status:** design checkpoint, not implementation.
> **Scope:** rebuild the front half of Learn Mode recognition while preserving Execute Mode and the existing draft/review/PathGraph-candidate display pipeline.

## Goal

把学习模式从“整屏模型直接画框并生成可点击坐标”改成“多来源解析 UI inventory，只对可交互候选做二阶段 grounding，再由 validator 决定能否进入学习草稿”。执行模式使用的模型、Operation、Gate、Trace、安全提交边界保持不变。

目标不是立即宣传一个大准确率，而是在后续 benchmark 中让关键分层指标逐步达到 90% 以上：

- `actionable_classification`
- `non_actionable_rejection`
- `grounding_point_inside_target`
- `coordinate_transform_replay`
- `draft_loader_compatibility`
- `pathgraph_candidate_validation`

任一指标样本不足时必须显示 `not_covered`，不能包装成模型准确率或端到端成功率。

## What Stays

以下后半段已经有价值，必须保留：

- `app.learn.model_trial.build_learning_model_trial()` 的 raw learning trial 输出入口。
- `learning_template_draft_v1` 的草稿展示形态。
- `app.learn.draft_review.load_learning_draft_review()` 的面板审阅模型。
- `save_reviewed_template_candidate()` 的人工补全候选。
- `app.learn.pathgraph_candidate.build_pathgraph_candidate_from_review()` 的 PathGraph candidate 生成。
- Learn Replay / Learning Studio 里“学习草稿”和“模板”分离展示。
- `artifact_is_authorization=false`、`execute_binding_enabled=false`、`real_action_requires_gate=true`、`final_submit_forbidden=true`。
- Execute Mode 的现有模型、识别运行、Gate、Trace、final submit guard。

## What Changes

旧主路径中这些部分需要清理或降级为兼容/诊断路径：

- `screen_map.candidates -> learn_all_targets` 直接进入坐标层。
- OCR-only 普通文字被当作 `safe_click_allowed`。
- `semantic_region_only` 中等置信模型 bbox 被当成可校准点击目标。
- 大卡片、代码块、正文、标题、只读列表被框成 Learn Deep 目标。
- 单一整屏模型同时负责页面理解、候选分类、坐标定位和草稿生成。

这些能力可以保留在 trace/诊断里，但不能再作为新学习模式的 primary recognition path。

## New Learn Recognition Pipeline

```text
Capture bound window
-> Observe evidence bundle
-> Parse screen inventory
-> Classify inventory items
-> Select actionable/form-field candidates
-> Build ROI crops
-> Ground locally
-> Restore coordinates
-> Validate evidence
-> Generate learning_template_draft_v1
-> Human review
-> PathGraph candidate
```

### 1. Observe Evidence Bundle

输入是当前绑定窗口截图，不执行点击：

```json
{
  "contract_version": "learn_observe_bundle_v1",
  "capture_id": "path-or-id",
  "screenshot_path": "artifacts/screenshots/...",
  "screenshot_sha256": "...",
  "viewport_size": {"width": 1920, "height": 1080},
  "app_identity": {
    "app_name": "python.org",
    "window_title": "...",
    "url": "https://..."
  },
  "sources": {
    "ocr": {},
    "uia": {},
    "dom": {},
    "vision_summary": {}
  }
}
```

### 2. Pluggable Parser

“可插拔 parser”只是候选来源插槽。它不授权点击，也不决定最终坐标。

每个 parser 只回答：屏幕上可能有什么？

推荐 parser provider：

- `ocr_parser`: 当前 OCR 文本框和文本行。
- `uia_parser`: Windows UIA 控件。
- `dom_parser`: 浏览器可用时的 DOM/accessibility 候选。
- `vision_semantic_parser`: Qwen3-VL 8B/更强 VLM 的整屏区域理解。
- `omniparser_parser`: OmniParser 输出的 icon/text/interactable 候选。
- `profile_rule_parser`: 项目已有的页面/软件 profile 规则。

统一输出：

```json
{
  "contract_version": "screen_inventory_item_v2",
  "item_id": "candidate_001",
  "label": "Search",
  "item_type": "actionable | form_field | readable | layout | blocker | danger_zone",
  "role": "button | input | link | text | card | section",
  "bbox": {"x": 0, "y": 0, "w": 1, "h": 1},
  "text": "Search",
  "source_evidence": ["ocr", "uia", "vision", "omniparser"],
  "interactable_evidence": {
    "uia_invokable": false,
    "dom_clickable": false,
    "omniparser_interactable": false,
    "vision_claim": true
  },
  "click_candidate": false,
  "risk_hint": "low | review | danger",
  "evidence_level": "ocr_text_only | semantic_region_only | multi_source_grounded"
}
```

Parser 合并规则：

- 多来源重叠候选合并为一个 item，保留所有 evidence。
- OCR-only 普通文本默认 `item_type=readable`、`click_candidate=false`。
- semantic-only bbox 默认 `click_candidate=false`，除非后续 grounding/validator 证明。
- danger/final-submit 词汇优先进入 `danger_zone`，不是普通 action。

### 3. Candidate Classification

分类器输入 inventory，输出可 grounding 的候选集合：

```json
{
  "contract_version": "learn_candidate_classification_v1",
  "accepted_for_grounding": [],
  "rejected_non_actionable": [],
  "needs_human_review": [],
  "danger_zones": []
}
```

必须拒绝：

- 标题、段落、正文、代码块。
- 只读卡片内容。
- 普通 OCR text line。
- layout container。
- decoration icon。
- 没有 UIA/DOM/OmniParser/action evidence 的 semantic-only 中等置信区域。

### 4. Two-Stage Grounding

只对 `actionable` / `form_field` 候选做定位。

第一阶段：粗 ROI。

```text
candidate bbox or region hint
-> expand 1.5x / 2.0x
-> clamp to screenshot
-> save crop metadata
```

第二阶段：局部定位。

```text
crop image
+ target description
+ nearby OCR
+ source evidence
-> grounding model
-> local bbox / local point
-> original screenshot coordinate
```

坐标还原必须记录：

```json
{
  "contract_version": "coordinate_transform_v1",
  "source_image_size": {"width": 1920, "height": 1080},
  "roi_bbox": {"x": 100, "y": 200, "w": 400, "h": 240},
  "crop_size": {"width": 800, "height": 480},
  "scale_x": 2.0,
  "scale_y": 2.0,
  "local_point": {"x": 320, "y": 180},
  "screen_point": {"x": 260, "y": 290}
}
```

### 5. Grounding Validator

任何点位进入学习草稿前必须通过 validator：

```json
{
  "contract_version": "learning_grounding_validation_v1",
  "status": "valid_candidate | needs_human_review | rejected",
  "checks": {
    "point_inside_bbox": true,
    "bbox_inside_image": true,
    "ocr_anchor_overlap": true,
    "uia_or_dom_or_parser_overlap": true,
    "coordinate_transform_replay": true,
    "screenshot_freshness": true,
    "not_non_actionable_content": true,
    "not_danger_zone": true
  }
}
```

失败行为：

- `rejected_non_actionable`: 不进坐标层，只留页面详情。
- `rejected_ungrounded`: 不进路径图候选。
- `needs_human_review`: 可以面板展示，但不能授权 Execute。
- `danger_zone`: 只进入安全/阻断区，不能变普通 action。

### 6. Draft Output

新识别层输出仍然喂给现有后半段：

```json
{
  "contract_version": "learning_template_draft_v1",
  "screen_summary": "...",
  "state_guess": "...",
  "states": [],
  "regions": [],
  "action_templates": [],
  "blockers": [],
  "verification_rules": [],
  "agent_decision_points": [],
  "operation_skills": [],
  "gate_contracts": [],
  "learning_source": "learn_recognition_pipeline_v2",
  "evidence_refs": {
    "observe_bundle_path": "...",
    "screen_inventory_path": "...",
    "grounding_report_path": "...",
    "validation_report_path": "..."
  },
  "safety": {
    "artifact_is_authorization": false,
    "execute_binding_enabled": false,
    "real_action_requires_gate": true,
    "final_submit_forbidden": true
  }
}
```

## Model Experiment Matrix Under 12B

执行模式模型保持不变。以下只允许用于学习模式实验。

| Component | Candidate | Public scale | Role | First use |
| --- | --- | ---: | --- | --- |
| Parser | OmniParser v2 | toolchain, not one VLM | screen parsing / interactable hints | Optional parser provider |
| Whole-screen understanding | Qwen3-VL-8B | 8B | page summary, region semantics, blockers | Existing/primary |
| Grounding | UGround-V1-2B | 2B | target -> pixel point | Lightweight test |
| Grounding | UGround-V1-7B | 7B | target -> pixel point | Main grounding candidate |
| Grounding + verifier | GUI-Actor-3B | 3B | coordinate-free action regions | Candidate verifier |
| Grounding + verifier | GUI-Actor-7B | 7B | coordinate-free action regions | Main verifier candidate |
| VLA trial | ShowUI-2B | 2B | trial model / comparison | Optional |
| Whole-screen stronger trial | Qwen3-VL under 12B available variant | <=12B | stronger parse/draft trial | Optional |

Download/experiment rules:

- 下载前必须创建 `configs/model_profiles/learn_mode_*.json`，不能覆盖 Execute Mode profile。
- 每个模型输出都要保存 raw input/output、model config、screenshot checksum、parsed result、failure taxonomy。
- 只有 `actual_model_call` 或合规 `recorded_output_per_config` 才能计入 model ability。
- Parser/tool 通过不能宣传成模型能力。
- 任一模型不能绕过 Gate 或 final-submit guard。

References:

- OmniParser GUI screen parsing: https://github.com/microsoft/omniparser
- UGround GUI grounding: https://osu-nlp-group.github.io/UGround/
- GUI-Actor coordinate-free grounding: https://microsoft.github.io/GUI-Actor/
- ShowUI GUI visual agent: https://arxiv.org/abs/2411.17465
- ScreenSpot-Pro high-resolution GUI grounding benchmark: https://arxiv.org/abs/2504.07981

## Benchmark Plan

新增 `learn_recognition_golden_manifest_v1.json`，不要复用 SEEK MVP 成功率口径。

第一版 20-30 个样本：

- `ocr_text_header_rejected`
- `code_block_rejected`
- `readable_card_rejected`
- `semantic_only_bbox_rejected`
- `button_grounding_success`
- `input_grounding_success`
- `grounding_point_miss`
- `coordinate_transform_replay`
- `roi_crop_edge`
- `wrong_surface_rejected`
- `danger_zone_rejected`
- `final_submit_rejected`
- `modal_blocker_detected`
- `pathgraph_candidate_loader_compatible`

指标：

```json
{
  "parse_inventory": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "actionable_classification": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "non_actionable_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "grounding_point": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "coordinate_transform": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "danger_zone_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
  "pathgraph_candidate_validation": {"passed": 0, "attempted": 0, "rate": "not_covered"}
}
```

## Clean-Up Rules

The old Learn Mode code should be cleaned in this order:

1. Mark old `learn_all_targets` as compatibility/diagnostic, not primary Learn Recognition.
2. Keep its overlay for debugging, but do not feed it directly to draft generation.
3. Preserve Learning Draft Review and DraftGraph Preview.
4. Preserve PathGraph candidate generation.
5. Remove or hide UI buttons that imply old coordinates are reliable learning output.
6. Add new Learning Recognition experiment entry points beside the existing display-only review pipeline.

## Acceptance Criteria For This Rebuild

The rebuild is not accepted until all are true:

- Execute Mode tests still pass and Execute model profiles are untouched.
- Learning mode can run a fixture/screenshot through parser -> classifier -> ROI -> grounding -> validator -> draft.
- Draft can be loaded by Learning Draft Review.
- Reviewed draft can generate PathGraph candidate.
- Non-actionable content rejection is benchmarked.
- Grounding point and coordinate transform are benchmarked.
- Report clearly separates parser/tool pass, model-generated pass, assisted generation, and fixture pass.
- No live submit, no live safe fill, no Execute authorization from learning artifacts.

## OmniParser Shadow Integration Checkpoint (2026-08-19)

`screen_parser_result_v1` is now a read-only optional parser input for learning recognition. The panel copies only a canonical latest observe result from either `omniparser` or `sources.omniparser` into observation evidence without rewriting the provider payload. Recognition emits `learning_recognition_provider_summary_v1` with provider state, profile/model revision, capture/SHA presence, element/interactivity/grounding/review-only/invalid-bbox counts, lineage warnings, provider error, and `execution_authorized=false`.

The review UI presents these as four deliberately separate facts: provider success, candidates generated, grounding eligibility, and execution authorization. Provider failure or incomplete lineage remains visible; parser interactivity is never presented as click permission and the panel adds no parser Execute control.

The only verified OmniParser smoke is the pinned offline artifact `D:\agent-gui-runtime\artifacts\omniparser-smoke\task2-round2-code-revision-final.json` (SHA-256 `dce1d24fbbf74d17292eebf600328e33815ca871f8a5bad6b741fa438b01ba5a`). It measured a cold run of `1520.17 ms`, warm P50/P95 of `463.84/465.58 ms`, and `43` elements (`35` interactive, `0` invalid bbox). Its input is a contact sheet only: it is not UI-accuracy evidence, live-capture evidence, or live-click evidence.

License review remains intentionally unresolved: the OmniParser repository root states CC-BY-4.0 while its README badge says MIT; detector licensing is AGPL and caption licensing is MIT. Any future use must enforce the exact component manifest rather than treating this checkpoint as a blanket license decision.
