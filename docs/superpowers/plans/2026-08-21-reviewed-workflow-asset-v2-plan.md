# Reviewed Workflow Asset v2 实施计划

1. 以 TDD 新增 v2 canonical contract、validator 和内容 hash。
2. 新增独立 content-addressed store 与 CAS registry，验证无 v1 migration。
3. 从 canonical `single_application_workflow_review_v1` 编译 state/transition/lineage。
4. 新增 offline replay coordinator：state resolution、transition selection、semantic verification、recovery decision。
5. 强化 approved-plan capture lineage，真实执行前拒绝 stale plan。
6. 新增 compile/publish/preview API，并将 summary 投影到 workflow review context。
7. 在现有 workflow 面板增加最小状态条和只读 preview。
8. 用全新合成 SEEK homepage/detail/apply-entry fixture 跑端到端测试。
9. 建立 Bare Agent 与 Runtime 的合同、成功/失败分类、延迟和 evidence 完整性基准。
