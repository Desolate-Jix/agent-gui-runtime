REVIEW_TOKEN_STAGE2_V104_FOOTER_BBOX_TIGHTENING_20260709

Please review these three separate Learning Mode page-detail preview images.

Context:
- This checkpoint is v104.
- v103 attached Python.org `>>More` to the right event list group, but the list-group parent bbox became too wide/tall because the far-right footer was included in the parent bbox union.
- v104 keeps the semantic attachment (`list_group_footer`) but, when a footer is horizontally detached from the row column, it does not expand the list group bbox. This is display-only evidence.
- AppleMusic and QQ are protected regression surfaces. They should not gain synthetic list/footer groups or lose their existing page-detail structure.
- The panel source picker now pins v104 demo scaffolds first.

Evidence:
- Python.org: `logs/benchmarks/learn_two_stage_python_v104_footer_bbox_tightening/learn_page_detail_candidate_preview.png`
- AppleMusic: `logs/benchmarks/learn_two_stage_applemusic_v104_footer_bbox_tightening/learn_page_detail_candidate_preview.png`
- QQ: `logs/benchmarks/learn_two_stage_qq_v104_footer_bbox_tightening/learn_page_detail_candidate_preview.png`

Please answer in this exact reviewer format:

1. Overall verdict: PASS / CONDITIONAL PASS / FAIL.
2. Python.org verdict: is the right event list-group parent bbox less bloated than v103, and does `>>More` still have an understandable review-only relationship to that group?
3. AppleMusic verdict: did v104 introduce any obvious regression or footer/list pollution?
4. QQ verdict: did v104 introduce any obvious regression or footer/list pollution?
5. Remaining review-only issues, if any.
6. Explicitly confirm this is only display-only page-detail / readonly PathGraph scaffold evidence, not Execute authorization, not Runtime PathGraph promotion, not live click/fill/submit, not recognition accuracy, and not E2E stability.
