# Reviewed Workflow Asset v2 实施计划

1. **完成**：以 TDD 新增 v2 canonical contract、validator 和内容 hash。
2. **完成**：新增独立 content-addressed store 与 CAS registry，验证无 v1 migration。
3. **完成**：从 canonical `single_application_workflow_review_v1` 编译 state/transition/lineage。
4. **完成（离线）**：新增 replay coordinator 的 state resolution、transition selection、semantic verification 和 recovery decision；首个里程碑仅启用 `open_detail` / `open_apply_flow` / `back` / `close_modal`，且 replay adapter 每次 action request 只允许一个 attempt。`read` / `scroll` 等待专用 effect verifier。
5. **部分完成**：approved-plan capture lineage 和 stale-plan 拒绝已强化；生产 current-observation capture 与 live execute orchestrator 尚未接线。
6. **完成**：新增 compile/publish/preview API；preview 为显式 observation 的只读非授权路径。
7. **完成**：现有 workflow 面板已接 Compile、CAS Publish、只读 Preview，并实现 binding/generation/dirty-state 失效保护。
8. **完成（纯离线）**：全新合成 SEEK homepage/detail/apply-entry fixture 贯穿真实 compiler/CAS/API/replay/adapter envelope，外部依赖为 fake，不含真实 GUI、网络或 action。
9. **完成（纯离线合同基准）**：外部 checksum manifest 固定 asset/cases；用 ordered recorded Bare events 与 Runtime replay 比较分类、停止、有限恢复、延迟和派生 evidence digest。该结果不是 live Bare Agent、模型或感知准确率。本轮未合入未证明安全的 recovery-feedback 持久化 store。
