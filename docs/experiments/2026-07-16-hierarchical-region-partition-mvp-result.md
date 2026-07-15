# Hierarchical Region Partition MVP Result

## Scope

This was an isolated, read-only shadow experiment. It did not modify `bar_detection_v1`, Execute, PathGraph, or safety gates. Five saved screenshots were evaluated with one Qwen3-VL 8B organization call per screenshot and no repair call.

## Result

Verdict: **not ready, and not better than the current bar-first path on this evidence**.

| Sample | Old issue | Hybrid result | Validator | Crop meaning | Verdict |
| --- | --- | --- | --- | --- | --- |
| Steam single column | false bottom-region split | one near-full content region | failed: empty root parent | geometry only | partial, not accepted |
| WhatsApp | rail/list/chat hierarchy incomplete | all candidates collapsed into one window region | failed | unusable for pane ROI | worse |
| Apple Music | broad overlapping bar regions | content rows partly found; controls omitted; duplicate children | failed | partial | partial, not accepted |
| Notepad | simple surface over-segmentation | toolbar/status duplicated; editor omitted | failed | unusable | worse |
| Python.org | old control sample broadly usable | duplicate full-page regions; columns lost | failed | unusable | severe regression |

The acceptance requirement of improving at least two known false/missed splits without severe regressions was not met.

## Diagnosis

- Candidate generation is still mostly element-level OCR/UIA/vision boxes. It does not yet provide strong anonymous separator, whitespace, or cluster-backed region proposals.
- Blank but meaningful areas, especially the Notepad editor, lack candidate support.
- Broad containers compete with detailed candidates and encourage all-candidate unions.
- The 8B organizer produced empty `parent_id`, duplicate regions, and, in the first protocol attempt, candidate IDs that did not exist.
- Original-image bbox union, overlays, and crop generation did not show a new coordinate transform drift.
- The independent validator correctly surfaced failures instead of converting them into a pass.

## Evidence

- Actual model report: `logs/region_partition_mvp/run_20260716_actual_v2/hierarchical_region_partition_mvp_report.json`
- Three-image audit: `logs/region_partition_mvp/run_20260716_three_image_audit/`
- Machine conclusion: `logs/region_partition_mvp/feasibility_conclusion.json`

## Next Experiment

Do not integrate this MVP into production. The next bounded experiment should first create true anonymous region proposals from separators, whitespace, connected element clusters, and large containers, then constrain model output so candidate IDs and parent IDs cannot leave the supplied sets. Re-evaluate on the same development screenshots plus untouched holdout screenshots.

