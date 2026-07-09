REVIEW_TOKEN_STAGE2_V102_READONLY_PATHGRAPH_SCAFFOLD_20260709

请作为视觉审核 reviewer，审核这次 Learning Mode v102 的阶段性结果。目标不是判断执行成功率，而是判断 page-detail 布局是否足够作为“只读 PathGraph 预览”的展示依据。

本轮代码变化：
- `scripts/build_learn_demo_scaffold.py` 对 direct `learn_page_detail_candidate_v1` 新增 `page_detail_readonly_pathgraph_preview_v1`。
- 这个 preview 复用同一套 `layout.sections` / `layout.regions` / `layout.display_groups`，只用于面板展示。
- `app/web_panel/panel.js` 会把它显示为 `Read-only PathGraph page detail preview`，与 model-only preview 分开。
- 不启动模型，不点击，不填表，不提交，不授权 Execute，不 promotion Runtime PathGraph。

请审核三张图：
1. Python.org v101/v102 page-detail layout：`42` regions / `4` sections / `2` display groups；v102 scaffold shared sections=`4`，shared display groups=`2`。
2. AppleMusic v101/v102 page-detail layout：`46` regions / `3` sections / `0` display groups；v102 scaffold shared sections=`3`。
3. QQ v101/v102 page-detail layout：`91` regions / `6` sections / `0` display groups；v102 scaffold shared sections=`6`。

请按以下格式回答：

Overall verdict: PASS / CONDITIONAL PASS / FAIL

Per-image verdict:
- Python.org:
- AppleMusic:
- QQ:

Review questions:
1. 这些图是否能作为 direct page-detail -> read-only PathGraph preview 的展示依据？
2. Python.org 的 list groups 是否比单独 list rows 更容易理解父子关系？
3. AppleMusic 是否没有被 list group / readonly preview 接入污染？
4. QQ 的右侧群友栏、公告/成员边界、消息区域是否仍应保持 review-only？
5. 是否可以把 v102 描述为“display-only page-detail / readonly PathGraph preview scaffold connected”？
6. 请明确禁止把它解释成 Runtime PathGraph 可执行、Execute 授权、点击安全、模型准确率、E2E 成功率或 live submit/fill 覆盖。

如果你认为还不能通过，请指出具体视觉问题和下一步最小通用修复方向。不要建议站点专用 hardcode。
