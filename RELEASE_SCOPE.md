# test.3 发布范围 / Release scope

从test.2干净发布分支增量更新；运行代码取自已完成Codex实机及AionUi独立复验的冻结候选06，最终目录只另改公开文档和验收摘要。未从脏开发树重新生成运行时、未复制学习/UI工作区变更、模型、环境或用户数据。 / Incremental on the clean test.2 release branch. Runtime bytes match frozen candidate06, tested first by Codex then AionUi; only public documentation/evidence summaries change afterward. No fresh runtime copy from the dirty development tree, models, environments or user data.

分支 `codex/release-instant-test-3` 用于即时执行第三批测试版，不替代完整产品开发分支。新增右击/双击、当前截图读文和本次启动窗口正常关闭，修复公共字段/菜单/词几何问题；不新增学习或审批功能。 / Instant execution test.3 branch, separate from full-product development; right/double click, visible-text reading, owned-window closure and shared targeting/OCR fixes, not new learning/approval features.

依赖导入、无输入测试、真实MCP和真实网页效果分别记录。438项源码、270项交付子集有重叠，不相加；独立22项只代表一轮真实网页，不是长期稳定证明。历史偶发双击/缺帧与跨设备验收仍开放。详见FIXES.md及release-verification.json。 / Import, no-input, stdio and real-page evidence are separate; overlapping checks are not additive. One live round does not close historical intermittency or cross-device acceptance.
