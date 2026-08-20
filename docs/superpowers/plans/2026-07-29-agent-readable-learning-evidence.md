# Agent 可读学习证据实施计划

## Checkpoint 1：契约与测试

- 新增 `agent_evidence_context_v1` 测试。
- 覆盖固定/动态内容、跳转、缺失语义、坐标剥离和 final-submit 安全。
- 先确认测试失败。

## Checkpoint 2：语义编译器

- 新增独立 Agent evidence 编译模块。
- 从单界面资产、应用图和旧 UI hierarchy 生成语义投影。
- 保留旧字段兼容，不改变 Execute、Gate 或 Trace。

## Checkpoint 3：旧资产迁移

- 新增非破坏式迁移脚本。
- 每个旧界面旁生成 `agent_evidence.json`，不改写 `interface.json`。
- 输出 readiness、缺失字段和 legacy candidate 数量。

## Checkpoint 4：接入 Agent 上下文

- 工作流 Agent context 增加编译后的证据视图。
- 原始 `workflows` 暂时保留，避免破坏 API。
- 任何缺少语义的旧资产保持 `needs_human_review`。

## Checkpoint 5：验证与文档

- 运行定向测试和相关回归。
- 对当前 SEEK 资产执行迁移并检查报告。
- 同步 README、ARCHITECTURE、PROJECT_SUMMARY、CURRENT_STATE 和 NEXT_STEPS。

