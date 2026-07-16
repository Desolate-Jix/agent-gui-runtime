# Hierarchical Region Partition MVP-2 Result

## Scope

This was an isolated, read-only A/B experiment on three saved screenshots. It did not modify or call Execute, PathGraph, production Stage1, `bar_detection_v1`, or safety gates. The Qwen3-VL 8B model was called exactly once for A and once for B on each screenshot with temperature `0.0`, `3072` output tokens, and no repair prompt.

- Experiment A: cleaned atomic element boxes.
- Experiment B: deterministic anonymous coarse proposals.
- Both sides used the same prompt organization rules, model, parser, compiler, crop code, and validator.

## Result

Status: **promising_but_mvp2_gate_not_passed**.

| Sample | Element-only result | Coarse proposal quality | Model organization | Validator | Crop usability | Better than baseline |
| --- | --- | --- | --- | --- | --- | --- |
| WhatsApp | 96 atomic boxes; toolbar and most content collapsed into broad unions; pane structure was not recovered | good: 78 px icon rail, 351 px conversation list, and 523 px empty chat area; two optional list children | failed: the model selected the useful panes but also created a full-window parent, duplicated pane roots, mis-grouped children, and emitted empty Level-1 `parent_id` | A fail / B fail | all B crops were generated, but duplicated hierarchy makes the tree unsafe to consume | structurally improved evidence; final tree not accepted |
| Notepad | only top controls and bottom status were represented; the blank editor had no candidate | good: top controls, a 1261 px-high element-free editor remainder, and bottom status; no duplicate editor proposal | failed: the model selected all three proposals but absorbed the editor into a full-window root and emitted only top/status children; Level-1 `parent_id` was empty | A fail / B fail | geometry and crops are usable for review; editor was not emitted as its own model region | yes for missing-area recovery; final tree not accepted |
| Python.org | 96 atomic boxes collapsed into a full-page root and duplicate full-page child | good: three page-level horizontal proposals; local lower columns no longer cut through the browser/header/hero | sensible selection of all three horizontal regions, but every Level-1 `parent_id` was empty and no parent-child hierarchy was expressed | A fail / B fail | three region crops align with original-image coordinates | clearly better partition structure; final tree not accepted |

Validator pass counts remained `0/3` for A and `0/3` for B. Therefore MVP-2 did not satisfy the required validator-improvement gate, even though B produced visibly better structure on at least two samples.

## Direct Answers

1. **Did coarse proposals recover missing regions?** Yes. The proposal layer explicitly recovered the blank Notepad editor and WhatsApp's sparse right chat area. It also prevented Python.org's local lower columns from becoming page-wide vertical partitions.
2. **Could the model correctly select and organize them?** Only partially. Python.org selection was geometrically sensible but hierarchy-free. Notepad preserved the editor only inside an all-proposal root. WhatsApp over-merged and duplicated regions. All three B outputs violated the required Level-1 `parent_id="root"` contract.
3. **Where is the current bottleneck?** The primary blocker in this run is model adjudication and schema compliance. Proposal generation still has secondary work around useful Level-2 children, but the three Level-1 proposal sets were reviewable and coordinate-correct.
4. **Is the direction worth a next stage?** The evidence justifies preserving the coarse-proposal direction and, if work continues, running one narrowly scoped adjudication-contract experiment. It does not pass the stated gate for production integration or broad benchmark expansion.
5. **Should it remain disabled by default?** Yes. It remains an isolated experiment with no runtime authorization.

## Attribution

- Proposal generation success: Notepad's blank editor was recovered without an application-specific rule; WhatsApp shared-edge alignment produced the rail/list boundary; Python.org local columns were prevented from becoming global columns.
- Model adjudication failures: empty Level-1 parent IDs in all six outputs, plus WhatsApp over-merge/duplication and Notepad's missing explicit editor child.
- Coordinate handling: proposal, model-union, overlay, and crop coordinates remained in original-image space; visual review found no new transform drift.
- Safety: zero clicks, zero fills, zero submits, no Execute binding, and no PathGraph promotion.

## Evidence

- A/B report root: `logs/region_partition_mvp2/actual_ab_v1/`
- Proposal review root: `logs/region_partition_mvp2/proposal_review/`
- Machine assessment: `logs/region_partition_mvp2/actual_ab_v1/mvp2_final_assessment.json`
- Per sample: `whatsapp/ab_comparison_report.json`, `notepad/ab_comparison_report.json`, and `python_org/ab_comparison_report.json`

## Recommended Next Work

Do not tune proposal geometry against these three outputs and do not add a repair prompt. If the experiment continues, isolate model adjudication with a constrained structural output protocol that cannot emit empty root parents or duplicate proposal ownership, then rerun the same frozen screenshots before adding new samples.
